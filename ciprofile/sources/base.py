#!/usr/bin/env python3
"""The source-adapter interface, and the discipline every adapter holds to.

A source answers four questions about a corpus and nothing else:

    candidates(limit)   which repositories there are to look at
    tree(repo, path)     what is in one directory of one repository
    file_text(repo, p)   the text of one file
    is_empty(repo)       whether the repository holds nothing at all

Everything above that line (where pipelines live, which grammar a file is in,
what its text says, how a repository is classified) is forge-agnostic and
lives in structure.py, rules.py and classify.py. Everything below it is one
forge's API. That seam is the whole point: the classification was written
against one forge and is worth nothing if it only runs there.

WHY `is_empty` IS PART OF THE INTERFACE
---------------------------------------
Because distinguishing "this repository has no pipeline" from "I could not
read this repository" is load-bearing, and the forges answer it differently.
A 404 on a root listing is ambiguous on its own: a repository with nothing in
it and a repository whose default branch is unborn or missing answer the same
way. Counting the second as the first turns a broken mirror, a failed import or
an unpushed default branch into evidence that a project does no CI;
`no-pipeline` is among the figures most likely to be quoted. The defect was
measured: two repositories in a 1428-repository corpus were being counted as
doing no CI when their default branch was unborn. See EXPERIMENTS.md,
"Distinguishing empty repository from could not read".

So the status code does not decide it. The adapter is asked, and it answers one
of three things:

    True   the repository is empty: the 404 is the absence of content, and
           `no-pipeline` is then a fact
    False  the repository is not empty: the 404 contradicts that, so the
           repository is recorded as unknown with the contradiction named
    None   the source did not say: nothing to decide on, so unknown again

None is not "not empty". An adapter that cannot tell says None, and the
repository leaves the distribution. That is the under-claiming direction, and
it is the rule everywhere here.

THE DISCIPLINE, AND WHY EACH PART OF IT EXISTS
----------------------------------------------
  - READ-ONLY BY CONSTRUCTION. Every adapter issues GET and nothing else;
    there is no write helper in any of them and none is wanted. This is what
    makes it acceptable to point the tool at a platform somebody else operates
    and to run it unattended. The test suite asserts it from the source rather
    than trusting it.
  - PACED, WITH A PER-ADAPTER FLOOR. The gap between requests is enforced in
    the transport, not at the call sites, so no caller can forget it, and it
    can be configured gentler but never sharper. A knob that can be set to
    zero is a knob that will be. The floors differ on purpose: an instance you
    operate and can watch is not the same as somebody else's production
    platform whose limits you cannot read.
  - ONE WORKER BY DEFAULT. Pacing happens inside the worker, so the worker
    count *is* the request rate. Two is the ceiling where the host is yours;
    there is no concurrency at all against a host that is not.
  - UNDER-CLAIM ON FAILURE. A repository that could not be read is recorded as
    unknown with the reason and excluded from every count. It is never counted
    as `no-pipeline`: that would turn every transient 503 into evidence of an
    absent pipeline.
  - REFUSE RATHER THAN PRODUCE A PARTIAL CORPUS SILENTLY. A distribution over
    an unannounced subset is the one output worth less than no output, because
    nothing about it looks wrong. Raise Refusal, or mark the result partial
    everywhere it is written and printed.
"""
import collections
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# What is in one directory. `type` is "file" or "dir", normalised by each
# adapter out of whatever its API calls them.
Entry = collections.namedtuple("Entry", "name type")

# One repository to look at. `key` is how it is named in the output
# ("owner/name"), `ref` is the branch to read, or None for the source's
# default, and `meta` is whatever the listing said, kept so an adapter can
# answer is_empty() without spending a second request.
Repo = collections.namedtuple("Repo", "key owner name ref meta")


def repo(key, owner=None, name=None, ref=None, meta=None):
    if owner is None or name is None:
        owner, _, name = key.partition("/")
    return Repo(key=key, owner=owner, name=name, ref=ref, meta=meta or {})


class Refusal(Exception):
    """Stop, and say why, rather than produce a corpus nobody asked for.

    Raised for the conditions where carrying on would mean publishing a figure
    over a population the run cannot describe: a sample size nobody chose, a
    listing that would not read, a corpus the source cannot enumerate.
    """


# What a status *means* to a caller, rather than what number it is. Every
# subtle bug in this area has been the same shape (an `if` that enumerated
# some statuses and quietly fell through on one it had not thought about), so
# the enumeration happens once and call sites branch on the meaning.
OK = "ok"                 # 2xx: it worked
ABSENT = "absent"         # 404: an answer, not a failure; there is no such thing
TRANSIENT = "transient"   # 0, 408, 429, 5xx: patience might change it
REFUSED = "refused"       # every other 4xx: the same request gets the same answer


def classify_status(status):
    """One of OK / ABSENT / TRANSIENT / REFUSED.

    The distinction that matters most is ABSENT versus everything else that is
    not OK. "There is no pipeline directory" and "I could not ask" are one
    digit apart and opposite in consequence.

    TRANSIENT exists because a network-level failure is reported as status
    **0**, which is below 300 and therefore passes a naive success test.
    """
    if 200 <= status < 300:
        return OK
    if status == 404:
        return ABSENT
    if status in (0, 408, 429) or 500 <= status < 600:
        return TRANSIENT
    return REFUSED


class Fetcher:
    """A GET-only, paced, counted HTTP client. The only transport here.

    GET-only by construction rather than by convention: there is no method
    parameter, so no call site can turn a read into a write, and the test suite
    asserts from the source that no other verb appears in any adapter.

    The pacing sleep happens after the response, so the gap holds across every
    call site and across failures too: a host that is refusing requests is the
    last one to hammer. The counter is incremented before the request, so a
    request that raises is still counted: an operator asking "what did this
    spend" must not be told less than the truth.
    """

    def __init__(self, base, pace, floor, headers=None, timeout=60):
        self.base = (base or "").rstrip("/")
        self.floor = floor
        self.pace = max(floor, pace if pace is not None else floor)
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.requests = 0
        self.last_rate_headers = {}

    def get(self, path, params=None, text=False, headers=None):
        """(status, body, response headers).

        `body` is parsed JSON, or the response text where `text` is set: raw
        file endpoints answer text/plain, and reading one as JSON would make
        every file unreadable.
        """
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        for k, v in list(self.headers.items()) + list((headers or {}).items()):
            req.add_header(k, v)
        self.requests += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                self._note_rate(r.headers)
                if text:
                    return r.status, raw.decode(errors="replace"), r.headers
                return r.status, (json.loads(raw) if raw else None), r.headers
        except urllib.error.HTTPError as e:
            self._note_rate(e.headers)
            return e.code, e.read().decode(errors="replace"), e.headers
        except OSError as e:
            # Deliberately the whole OSError family, not the ConnectionError
            # subset. A sweep runs for an hour against a remote host and the
            # transport fails in ways that are not connection resets: a laptop
            # changing network drops the source address, a VPN flap gives
            # EHOSTUNREACH, ephemeral ports run out under sustained churn.
            # None of those is a ConnectionError, so each one escaped as a
            # traceback and abandoned the run. Status 0 is what every caller
            # already treats as a failure it can retry, record or skip past.
            # urllib.error.URLError and TimeoutError are OSError subclasses and
            # are covered here.
            return 0, str(e), {}
        except ValueError as e:
            # A 2xx that is not the JSON it claims to be: a captive portal or
            # an error page served mid-request. Status 0, for the same reason.
            return 0, str(e), {}
        finally:
            time.sleep(self.pace)

    def _note_rate(self, headers):
        self.last_rate_headers = {
            k: v for k, v in (headers or {}).items()
            if k.lower().startswith(("ratelimit", "x-ratelimit"))}


def pace_from_env(var, floor):
    """The configured gap, never below the floor.

    Factored out so the clamp is testable without a socket, and so a run can be
    made *gentler* by configuration but never sharper.
    """
    raw = os.environ.get(var, "")
    try:
        asked = float(raw)
    except (TypeError, ValueError):
        asked = floor
    return max(floor, asked)


class Source:
    """What every adapter implements. See the module docstring.

    Subclasses set `name`, `PACE_FLOOR` and `WORKER_CEILING`, and implement the
    four methods. `limitations` is a list of sentences that travel into the
    output beside the figures they bear on: a limitation that lives only in a
    docstring is not one, because the JSON outlives the terminal.
    """

    name = "source"
    # The minimum gap between requests, in seconds.
    PACE_FLOOR = 1.0
    # How many workers this source may be swept with. Pacing is per worker, so
    # this number is a multiplier on the request rate.
    WORKER_CEILING = 1
    # True where the source makes no network call at all.
    offline = False
    limitations = []

    def candidates(self, limit=0):
        """[Repo] to classify. Raise Refusal rather than return a partial set.

        `limit` is a ceiling on how many to return, and a run that uses one
        writes a partial profile and says so: a prefix of a listing is not a
        sample. Where the listing is ordered by name it is not even close to
        one; see EXPERIMENTS.md, "Excluding organisation profile
        repositories", where 17 of the first 25 repositories by name were
        metadata repositories holding no software.
        """
        raise NotImplementedError

    def tree(self, repo, path=""):
        """(status, [Entry] or None, truncated).

        `truncated` says the listing was longer than this adapter will page
        through. Its caller must treat that as unreadable rather than as a
        complete listing: deciding "there is no pipeline file here" from part
        of a directory is the one conclusion that must never be reached on
        partial evidence.
        """
        raise NotImplementedError

    def file_text(self, repo, path):
        """(status, text) for one file; text None unless the status is 200."""
        raise NotImplementedError

    def is_empty(self, repo):
        """True / False / None. See WHY `is_empty` IS PART OF THE INTERFACE."""
        raise NotImplementedError

    # ---- shared

    def requests_made(self):
        http = getattr(self, "http", None)
        return http.requests if http is not None else 0

    def describe(self):
        """What the output says about where its figures came from."""
        http = getattr(self, "http", None)
        return {
            "source": self.name,
            "host": getattr(http, "base", None),
            "offline": self.offline,
            "read_only": True,
            "authenticated": bool(getattr(self, "authenticated", False)),
            "pace_seconds": getattr(http, "pace", 0.0),
            "pace_floor": self.PACE_FLOOR,
            "worker_ceiling": self.WORKER_CEILING,
            "requests": self.requests_made(),
            "rate_limit_headers_last_seen": dict(
                getattr(http, "last_rate_headers", {}) or {}),
            "limitations": list(self.limitations),
        }
