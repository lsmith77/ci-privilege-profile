#!/usr/bin/env python3
"""The evidence cache: what a sweep fetched, so a rule change costs nothing.

EVIDENCE, NOT CONCLUSIONS
-------------------------
The cache holds the pipeline file texts, the root listing's status, the
source's own emptiness answer and the foreign-CI markers at the root:
everything the classification reads, and no classification of its own. The
profile holds conclusions and lives in its own file, named nothing like this
one: a reader who finds either later must not have to work out which they are
holding.

That separation is what makes a cached re-analysis worth having. The rules are
re-run over the stored inputs, so a rule can be changed and the new answer
derived without a single request. That includes the emptiness rule, which is
among the most worth changing and which a cache of stored verdicts could only
repeat.

BUILD THE CACHE FIRST
---------------------
Two full sweeps of about a hundred minutes each were spent before this existed,
and every rule change cost another one. See EXPERIMENTS.md, "Caching the
fetched text, and doing it too late". If you are building something of this
shape: cache the fetched text in the first version, not the fourth.

A CACHED RUN IS NOT A MEASUREMENT, AND SAYS SO
----------------------------------------------
A cached re-analysis describes the corpus as it stood on the fetch date. Corpora
move: repositories are added, pipelines are rewritten. So every output carries
the banner below (in the first key of the JSON, above and below the printed
figures) and `scanned` is set to the oldest fetch date rather than to today,
with `reanalysed` saying when the rules ran.

IT REFUSES RATHER THAN DEGRADE
------------------------------
No cache, a cache this version cannot read, an undated one, or one a sweep
marked partial: refuse, naming what would fix it. A distribution over an
unannounced subset of the corpus is the one output worth less than no output,
because nothing about it looks wrong, and it would be quoted. A partial cache
is usable with ALLOW_PARTIAL_CACHE set, and then the reason travels in the
banner.
"""
import json
import os
import socket
import sys
from datetime import date

# Bumped whenever the cache has to carry something it did not carry before. A
# cache from an older version is refused rather than read for the fields it
# does have: the missing field is exactly the evidence the new rule needs.
CACHE_VERSION = 1
ALLOW_PARTIAL_CACHE = os.environ.get("ALLOW_PARTIAL_CACHE", "") \
    not in ("", "0")

COMMENT = (
    "EVIDENCE, NOT CONCLUSIONS. The pipeline file texts this tool fetched, "
    "with the root listing's status, the source's own emptiness answer and the "
    "foreign-CI markers at the root: everything the classification reads, so "
    "a re-analysis can re-run it over this corpus with no network access at "
    "all. It holds no classification of its own: the profiles live in the "
    "profile JSON, and anything derived from this file describes the corpus as "
    "it was on the fetch date each entry carries, which is not the same as the "
    "corpus now.")


class Recorder:
    """What one sweep fetched, keyed by repository, serialised at checkpoints.

    Filled as each repository is read rather than assembled afterwards: a
    checkpoint has to be able to write a usable cache mid-sweep, and anything
    assembled at the end would be missing the repositories whose requests had
    already been spent. An interrupted sweep's profile can be rebuilt by
    re-running; the requests it spent cannot.
    """

    def __init__(self, source_description=None):
        self.entries = {}
        self.source = source_description or {}

    def record(self, key, status, empty, files, other, reason):
        entry = {"fetched": date.today().isoformat(), "root_status": status,
                 "empty": empty}
        if reason:
            entry["reason"] = reason
        elif status == 200:
            entry["files"] = files
            entry["other_ci"] = sorted(other or ())
        # No files key for the empty-repository case: there was nothing to
        # fetch, and the replay gets that answer back out of the emptiness rule
        # rather than out of a stored `{}` that would look like a reading.
        self.entries[key] = entry

    def document(self, covered=(), partial=False, reason=""):
        missing = sorted(k for k in covered if k not in self.entries)
        if missing:
            partial = True
            reason = (reason + "; " if reason else "") + (
                "{} repositories were reported from a profile carried forward "
                "with no cache entry of their own, so their pipeline texts are "
                "not here; run a full sweep to fill them in".format(
                    len(missing)))
        dates = sorted(e["fetched"] for e in self.entries.values())
        today = date.today().isoformat()
        return {
            "$comment": COMMENT,
            "cache_version": CACHE_VERSION,
            "fetched_oldest": dates[0] if dates else today,
            "fetched_newest": dates[-1] if dates else today,
            "partial": bool(partial),
            "partial_reason": reason,
            "source": self.source,
            "repos": dict(sorted(self.entries.items(),
                                 key=lambda kv: kv[0].lower())),
        }

    def write(self, path, covered=(), partial=False, reason="", log=print):
        doc = self.document(covered, partial, reason)
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        size = os.path.getsize(path)
        log("wrote {}: {} repositories, {:.1f} MB".format(
            path, len(self.entries), size / 1e6)
            + ("; PARTIAL: " + doc["partial_reason"] if doc["partial"] else ""))
        return size


def read_cache(path):
    """The cache at `path`, or an exit saying why it cannot be used."""
    if not os.path.exists(path):
        sys.exit("no cache at {}. A cached re-analysis re-reads what a sweep "
                 "already fetched; run a sweep once to write one. Nothing on "
                 "this path will fetch it, by design.".format(path))
    try:
        with open(path) as fh:
            cache = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit("{} is unreadable ({}). Move it aside and re-run the sweep; "
                 "nothing here will re-fetch it.".format(path, e))
    if cache.get("cache_version") != CACHE_VERSION:
        sys.exit("{} is cache_version {!r}, and this is version {}. Refusing "
                 "rather than reading the fields it does have: a version is "
                 "bumped because the cache has to carry something new, so the "
                 "field missing from the old one is exactly what the new rules "
                 "need. Re-run the sweep.".format(
                     path, cache.get("cache_version"), CACHE_VERSION))
    if not isinstance(cache.get("repos"), dict) or not cache["repos"]:
        sys.exit("{} holds no repositories, so there is nothing to re-analyse."
                 .format(path))
    for key in ("fetched_oldest", "fetched_newest"):
        if not cache.get(key):
            sys.exit("{} does not say when it was fetched ({} is missing), so "
                     "nothing produced from it could say either. Refusing: an "
                     "undated re-analysis is indistinguishable from a "
                     "measurement.".format(path, key))
    if cache.get("partial") and not ALLOW_PARTIAL_CACHE:
        sys.exit("{} is marked partial ({}). Refusing: a distribution over a "
                 "subset of the corpus that does not announce itself is worse "
                 "than none. Re-run the sweep, or set ALLOW_PARTIAL_CACHE=1 if "
                 "the smaller corpus is what you want; every output then says "
                 "so.".format(path,
                              cache.get("partial_reason")
                              or "no reason recorded"))
    return cache


def banner(cache):
    """The line no output derived from a cache may appear without."""
    span = cache["fetched_oldest"]
    if cache["fetched_newest"] != span:
        span += " to " + cache["fetched_newest"]
    line = ("RE-ANALYSED FROM A CACHE FETCHED {}: this describes the corpus "
            "as it was then, NOT as it is now, and NOT a fresh measurement. "
            "Corpora move: repositories are added, pipelines are rewritten, "
            "and nothing here has been re-read from any host.".format(span))
    if cache.get("partial"):
        line += (" THE CACHE IS ALSO PARTIAL ({}), so these figures cover a "
                 "subset of the corpus.".format(
                     cache.get("partial_reason") or "no reason recorded"))
    return line


def forbid_network(reason="this path must not reach the network"):
    """Make a network call impossible, not merely unintended.

    A cached re-analysis's whole claim is that it costs nothing, and a
    docstring cannot keep that true: an edit that reached for one more field
    would reach a host, and against a CPU-capped instance nobody would notice.
    So the socket layer is taken away before the cache is even opened, and a
    call added anywhere on this path raises instead of spending a request.

    The connecting and the resolving, not the socket class itself: `ssl`
    subclasses that class at import, so replacing it breaks any module imported
    afterwards and the failure then says nothing about this guard. A socket
    that cannot connect and a name that cannot resolve is the same guarantee
    without that trap.
    """
    def refuse(*_args, **_kw):
        raise AssertionError(reason)

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    socket.gethostbyname = refuse
