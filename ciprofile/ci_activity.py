#!/usr/bin/env python3
"""Does the declared pipeline actually run? Upstream workflow activity.

    GITHUB_TOKEN=... python3 -m ciprofile.ci_activity \
        --profile data/ci_profile.json --fork data/fork_pr_profile.json

Writes ci_activity_profile.json. Reads GitHub's Actions REST API and nothing
else.

WHAT EVERY OTHER FIGURE IN THIS REPOSITORY COUNTS, AND THIS ONE DOES NOT
------------------------------------------------------------------------
The classifier reads pipeline *configuration*. A repository whose workflow
declares the pull-request event is counted as a repository that checks pull
requests, and the count is correct about the declaration and says nothing about
whether the declaration was ever acted on. A pipeline can have been committed
once and never have run anywhere.

That is not hypothetical. Of the repositories whose workflows failed under
differential execution, some have no recorded workflow run at all upstream, so
the local failure said nothing about the local runner and everything about the
pipeline being dead. This measurement asks the hosting forge what each
repository's workflows have actually done, which is the one thing reading the
text cannot establish.

TWO USES, AND THE SECOND IS A CONTROL
-------------------------------------
  1. **A figure of its own**: how much of the declared CI in a corpus works.
     Over the subset with a pull-request-triggered pipeline, how many have ever
     run a workflow, how many ran recently, how many never ran.
  2. **A control for differential execution.** An environment failure on a
     pipeline that passes upstream is a gap in the local runner's fidelity. The
     same failure on a pipeline with no upstream runs is a dead pipeline, and
     reading it as a fidelity gap would be reading an absence as a defect.
     `--differential` joins the two and says which each one is.

THIS MEASURES THE UPSTREAM, NOT THE PLATFORM HOLDING THE MIRROR
---------------------------------------------------------------
For a mirror corpus the runs counted here happened on the upstream host. They
are not activity on the forge the mirror lives on, which for a mirror runs no
pipeline at all. Every figure this prints says `upstream` for that reason, and
the honest reading of a zero is "this project's pipeline does not run where the
project is developed", never "this platform does not run CI".

THE JOIN, WHICH IS THE TRAP
---------------------------
The corpus keys repositories by the mirror's name and the upstream must be
asked about under its **current** name. Those differ: in the corpus this was
built against, several upstreams have been renamed or transferred since the
mirror was taken, so a join on the name alone loses them in one direction and a
join on the key alone in the other. Both names are recorded per repository.

Nothing new is invented to resolve this. The fork observation already did it,
and the two mechanisms it uses are reused here rather than re-derived:

  - `--upstream FILE`, read by `fork_observation.read_upstreams()`, which maps
    `corpus-key owner/name` and is the only thing that can state the upstream
    *host*, because a host cannot be guessed from a repository's name.
  - `--fork FILE`, a `fork_pr_profile.json`. Its per-repository
    `name_with_owner` is the upstream's name **as GitHub answered it**, so a
    rename or a transfer is already resolved there. Where both files cover a
    key, this one wins on the name, because it is an answer and the mapping
    file is an assertion.

Falling back to the corpus key as GitHub coordinates is allowed only where the
fork observation reached for that key and did not get an answer
(`query-unanswered`, `upstream-absent`): there the upstream was taken to be on
GitHub and only the response was missing. A key the fork observation recorded
as `host-unknown` or `non-github-upstream` is never guessed at, because those
two are statements about the host and overriding them with the key is exactly
the mistake this section exists to avoid.

UNKNOWN IS NOT ZERO
-------------------
A repository the API cannot answer for is recorded `unknown` with the reason.
It is never recorded as having never run. That distinction is the whole point
of the measurement: an unasked repository looks exactly like a dead one, and
the flattering mistake and the alarming mistake are the same mistake here.

`non-actions-pipeline` is the reason that matters most. A repository whose
pull-request scope is a GitLab, Woodpecker or Jenkins pipeline has no GitHub
Actions runs by construction, and counting its zero as a dead pipeline would be
counting the wrong API. Those repositories are not asked about at all. A
repository with workflows *and* another grammar is asked about and carries
`other_grammar_files`, because its zero is then only a zero for the Actions
half.

WHAT "RECENTLY" MEANS, STATED RATHER THAN LEFT TO THE READER
------------------------------------------------------------
A run is recent when it was created within RECENT_DAYS days of the measurement
timestamp. The window travels in the output and in every printed figure. It is
a window on the run's creation and not on the repository's commits: a project
that stopped being developed and whose last pipeline run passed is `passing`
only if that run is inside the window, and `ran-not-recently` otherwise,
because a green run from last year is not a working check today.

SIX STATUSES
------------
  - `never-ran`        the API reports no workflow run for the repository.
  - `ran-not-recently` runs exist and the newest is outside the window.
  - `passing`          a run inside the window, and the newest concluded run
                       concluded `success`.
  - `failing`          the newest concluded run failed, timed out, or failed at
                       startup.
  - `awaiting-approval`  the newest concluded run is `action_required`: a run
                       held at an approval gate, which is neither a pass nor a
                       failure of the pipeline.
  - `inconclusive`     the newest runs were cancelled, skipped, neutral, or are
                       still in flight. Nothing is claimed from them.
  - `unknown`          not answered. Carries the reason and is never a zero.

TWO REQUESTS A SCOPE, AND THE BUDGET IS READ RATHER THAN GUESSED
-----------------------------------------------------------------
`/repos/{owner}/{repo}/actions/runs` carries `total_count` beside the newest
page of runs, each with its `conclusion`, `event`, `created_at` and workflow
identity, and `?event=pull_request` restricts the same reading to the scope the
rest of this tool quotes. A second request per scope, `?status=success`, is
what makes `last_success_at` exact rather than "no success within the newest
page": the page is bounded and the probe is not.

So at most four requests per repository, and the authenticated hourly budget is
5000. It is read from the `x-ratelimit-*` response headers, never assumed, and
`RestBudget` reuses the fork observation's floor and its `check()`, so the one
place that decides when to stop is shared between the two measurements. Below
the floor the run stops, writes what it has, marks the file `partial`, and
records every unreached repository as `rate-budget-exhausted`.

READ-ONLY BY CONSTRUCTION
-------------------------
Every request is a GET. No verb is named anywhere in this module, so there is
no argument to get wrong, and the checks assert that.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .classify import PR_SCOPE
from .differential import ABSENT, workflow_paths
from .fork_observation import (Budget, RateBudgetLow, REASON_ABSENT,
                               REASON_BUDGET, REASON_HOST_UNKNOWN,
                               REASON_LIMIT, REASON_NON_GITHUB,
                               REASON_UNANSWERED, pace_seconds, read_profile,
                               read_upstreams)
from .report import ACTIVITY_NAME, refuse_overwrite

API = "https://api.github.com"
RUNS = "/repos/{}/{}/actions/runs"
ATTEMPTS = 3
# How many of the newest runs are read per scope. Enough to show the shape of
# the recent conclusions without paging: the status rests on the newest
# concluded run, and `last_success_at` comes from its own probe rather than
# from this page, so a longer page would buy nothing the status uses.
RECENT_RUNS = 20
# A run created within this many days of the measurement is recent. Printed
# with every figure derived from it, because "currently passing" is otherwise a
# claim whose window the reader has to guess.
RECENT_DAYS = 30

# Stop with this many requests still in hand: enough to finish the repository
# in flight and write the file.
RATE_FLOOR = int(os.environ.get("ACTIVITY_RATE_FLOOR", "60"))
PACE_SECONDS = pace_seconds(os.environ.get("ACTIVITY_PACE_SECONDS"))

# Scope labels, which are also the keys in the output.
ALL_EVENTS = "all_events"
PULL_REQUEST = "pull_request_event"

NEVER_RAN = "never-ran"
STALE = "ran-not-recently"
PASSING = "passing"
FAILING = "failing"
AWAITING = "awaiting-approval"
INCONCLUSIVE = "inconclusive"
UNKNOWN = "unknown"
STATUSES = [PASSING, FAILING, AWAITING, INCONCLUSIVE, STALE, NEVER_RAN,
            UNKNOWN]

STATUS_MEANS = {
    NEVER_RAN: "the API reports no workflow run for this repository",
    STALE: "runs exist and the newest is outside the recency window",
    PASSING: "a run inside the window, newest concluded run concluded success",
    FAILING: "the newest concluded run failed, timed out or failed at startup",
    AWAITING: "the newest concluded run is action_required: held at an "
              "approval gate, which is neither a pass nor a failure",
    INCONCLUSIVE: "the newest runs were cancelled, skipped or neutral, or are "
                  "still in flight. Nothing is claimed from them",
    UNKNOWN: "not answered. Carries the reason, and is NEVER a zero",
}

SUCCESS = "success"
FAILED_CONCLUSIONS = ("failure", "timed_out", "startup_failure")
AWAITING_CONCLUSION = "action_required"

# Why a repository was not asked about, or was asked and not answered. Each is
# its own reason because they call for different things, and none of them is a
# repository whose pipeline never ran.
REASON_NON_ACTIONS = "non-actions-pipeline"
REASON_UNAVAILABLE = "actions-unavailable"
REASON_NO_UPSTREAM = "upstream-name-unknown"

# The differential outcomes this measurement exists to control for: the three
# that prove nothing on their own. Spelled here rather than imported as a group
# because the grouping is this module's reading of them, not that module's.
PROVES_NOTHING = ("environment-failure", "timed-out", "not-attempted")

CONTROL_FIDELITY = "fidelity-gap"
CONTROL_DEAD = "dead-pipeline"
CONTROL_BROKEN = "failing-upstream-too"
CONTROL_STALE = "no-current-upstream-run"
CONTROL_UNDECIDABLE = "not-decidable"
CONTROL_ANSWERED = "local-run-answered"

CONTROL_MEANS = {
    CONTROL_FIDELITY: "it passes upstream and failed here, so the difference "
                      "is this environment",
    CONTROL_DEAD: "it has never run upstream either, so the local failure "
                  "says nothing about the local runner",
    CONTROL_BROKEN: "it fails upstream as well, so the failure is the "
                    "pipeline's and not this environment's",
    CONTROL_STALE: "it has run upstream but not inside the recency window, so "
                   "there is no current upstream run to compare against",
    CONTROL_UNDECIDABLE: "the upstream status is unknown, so neither reading "
                         "is available",
    CONTROL_ANSWERED: "the local run reached an answer on its own; the "
                      "upstream status is context and not a control",
}

SELECTION_RULE = [
    "the pull-request scope has a pipeline (its primary class is neither "
    "no-pipeline nor no-pull-request-trigger), which is the subset the rest of "
    "this tool quotes",
    "that scope holds at least one GitHub Actions workflow, because the "
    "Actions API can answer for no other grammar. A scope that holds none is "
    "`non-actions-pipeline` and is not asked about, never a zero",
    "an upstream name is established for it by the join described in the "
    "module docstring; a key with none is `upstream-name-unknown`",
]

LIMITATIONS = [
    "THIS IS THE UPSTREAM'S ACTIVITY. For a mirror corpus the runs counted "
    "here happened on the host the project is developed on, not on the forge "
    "holding the mirror, which runs no pipeline at all. A zero says the "
    "project's own pipeline does not run where the project is developed.",
    "`never-ran` means the Actions API reports no workflow run. Log and "
    "artifact retention do not remove run records, but a run deleted through "
    "the API, or a workflow whose runs were purged, is indistinguishable here "
    "from one that never ran.",
    "Repositories in `not_queried` were NOT measured, and not one of them is "
    "a repository whose pipeline never ran. `non-actions-pipeline` is the "
    "largest reason and the most important: a GitLab or Woodpecker pipeline "
    "has no Actions runs by construction.",
    "A repository carrying `other_grammar_files` has a pipeline in a second "
    "grammar as well, so its Actions figures cover only part of its CI.",
    "`passing` and `failing` rest on the newest CONCLUDED run inside the "
    "recency window. They describe that run, not the pipeline's history: a "
    "repository with a long record of failures whose newest run passed reads "
    "as `passing`.",
    "The recency window is this measurement's own choice and every figure "
    "derived from it moves if the window moves. It is recorded in the output "
    "for that reason.",
    "`total_count` counts runs of every workflow in the repository, and the "
    "pull-request restriction counts runs triggered by that event. Neither is "
    "a count of runs of the particular workflow a classification rested on.",
    "The control reading is based on the PULL-REQUEST-EVENT status, because "
    "that is the event differential execution runs. A repository with push "
    "runs and no pull-request runs is a dead pull-request pipeline and a live "
    "repository, and both figures are recorded so the two cannot be confused.",
]


# ---------------------------------------------------------------- transport

def token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        raise SystemExit(
            "GITHUB_TOKEN is not set: this needs a GitHub token (no scopes "
            "required; every repository queried is public)")
    return tok


class RestBudget(Budget):
    """The hourly REST budget as the API reports it, not as we guess at it.

    The floor, `low()` and `check()` are the fork observation's, inherited
    rather than restated, so the one decision about when to stop is shared
    between the two measurements. Only the reading differs: GraphQL banks a
    `rateLimit` object inside the response body, REST puts the same figures in
    the response headers, and a request costs exactly one.
    """

    def __init__(self, floor=None):
        Budget.__init__(self, RATE_FLOOR if floor is None else floor)

    def observe_headers(self, headers):
        if not headers:
            return
        low = dict((str(k).lower(), v) for k, v in dict(headers).items())
        banked = {"cost": 1}
        for header, key in (("x-ratelimit-limit", "limit"),
                            ("x-ratelimit-remaining", "remaining"),
                            ("x-ratelimit-used", "used")):
            try:
                banked[key] = int(low[header])
            except (KeyError, TypeError, ValueError):
                pass
        try:
            banked["resetAt"] = datetime.fromtimestamp(
                int(low["x-ratelimit-reset"]), timezone.utc).replace(
                    microsecond=0).isoformat()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            pass
        self.observe(banked)

    def check(self):
        """`low()` and the floor are inherited, so the decision is the shared
        one. Only the noun changes: a REST budget is counted in requests, and
        calling them points would send a reader to the wrong documentation."""
        if self.low():
            raise RateBudgetLow(
                "{} of {} requests left (floor {}), resets at {}".format(
                    self.remaining, self.limit, self.floor, self.reset_at))

    def summary(self):
        s = Budget.summary(self)
        s.pop("node_count_this_run", None)
        s["requests_this_run"] = s.pop("spent_this_run")
        s["unit"] = "requests per hour"
        return s


# The one HTTP call site, stubbed wholesale by the offline checks, which also
# take the socket layer away so a stub that fell through would fail rather than
# reach GitHub. No verb is named: a Request with no body is a GET, and a module
# that never spells a verb has no verb to get wrong.
def get(path, tok, timeout=60):
    req = urllib.request.Request(API + path)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r), dict(r.headers)


def rest(path, tok, budget, label=""):
    """(payload, reason). Exactly one of the two is None.

    A reason is never "this repository has no runs": every failure mode here
    produces an `unknown`, which is the distinction the whole measurement
    rests on. RateBudgetLow is raised *before* a call rather than after, so the
    caller stops with enough budget left to write its results.
    """
    budget.check()
    for attempt in range(1, ATTEMPTS + 1):
        if budget.requests:
            time.sleep(PACE_SECONDS)
        budget.requests += 1
        try:
            body, headers = get(path, tok)
        except urllib.error.HTTPError as e:
            budget.observe_headers(getattr(e, "headers", None))
            if e.code == 401:
                raise SystemExit(
                    "GitHub rejected the token (HTTP 401). Nothing was "
                    "measured. Fix the credential rather than re-running.")
            if e.code == 404:
                return None, REASON_ABSENT
            if e.code == 403:
                # Either the hourly budget is gone or Actions is not available
                # on this repository, and the header says which. Reading it
                # the other way round would record a dead pipeline where there
                # is a spent budget, which is the one misreading that would
                # look like a finding.
                if budget.remaining is not None and budget.remaining <= 0:
                    raise RateBudgetLow(
                        "{} of {} requests left, resets at {}".format(
                            budget.remaining, budget.limit, budget.reset_at))
                return None, REASON_UNAVAILABLE
            wait = 0
            try:
                wait = int(e.headers.get("Retry-After") or 0)
            except (AttributeError, TypeError, ValueError):
                wait = 0
            print("  {} attempt {} HTTP {}{}".format(
                label, attempt, e.code,
                ", Retry-After {}s".format(wait) if wait else ""),
                file=sys.stderr)
            time.sleep(wait or 5 * attempt)
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError) as e:
            print("  {} attempt {} failed: {}".format(label, attempt, e),
                  file=sys.stderr)
            time.sleep(5 * attempt)
            continue
        budget.observe_headers(headers)
        return body, None
    return None, REASON_UNANSWERED


def runs_path(owner, name, event=None, per_page=1, status=None):
    """The Actions runs endpoint for one repository and one scope.

    Owner and name arrive from somebody else's dataset, so they are
    percent-encoded rather than trusted to stay inside GitHub's own character
    set, and every query value is forced to a known shape here.
    """
    def q(v):
        return urllib.parse.quote(str(v), safe="")
    query = ["per_page={}".format(int(per_page))]
    if event:
        query.append("event=" + q(event))
    if status:
        query.append("status=" + q(status))
    return RUNS.format(q(owner), q(name)) + "?" + "&".join(query)


# ---------------------------------------------------------------- reading

def parse_time(stamp):
    """A GitHub timestamp as an aware datetime, or None.

    Zulu only, which is what the API emits. Anything else is not guessed at,
    because a timestamp read wrong moves a repository between `passing` and
    `ran-not-recently` silently.
    """
    try:
        return datetime.strptime(
            str(stamp)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def read_runs(body):
    """(total, [run]) from a runs payload, newest first.

    `total` is None where the payload did not carry an integer `total_count`,
    which the caller turns into an `unknown`. The ordering is imposed here
    rather than taken from the response: the endpoint answers newest first, and
    a status that rests on "the newest run" should not rest on that staying
    true.
    """
    if not isinstance(body, dict):
        return None, []
    total = body.get("total_count")
    if isinstance(total, bool) or not isinstance(total, int):
        return None, []
    runs = []
    for r in (body.get("workflow_runs") or []):
        if not isinstance(r, dict):
            continue
        runs.append({"conclusion": r.get("conclusion"),
                     "status": r.get("status"),
                     "event": r.get("event"),
                     "created_at": r.get("created_at"),
                     "workflow": r.get("name"),
                     "workflow_id": r.get("workflow_id")})
    runs.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return total, runs


def conclusion_counts(runs):
    counts = {}
    for r in runs:
        key = r.get("conclusion") or ("in-flight: " + str(r.get("status")))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def derive_status(record, recent_days, now):
    """One scope's status, from its own figures and nothing else."""
    if not record.get("ever_ran"):
        return NEVER_RAN
    last = parse_time(record.get("last_run_at"))
    if last is None:
        # Runs are counted and none came back on the page. Not a zero and not
        # a verdict: an answer this reading cannot use.
        return INCONCLUSIVE
    if now - last > timedelta(days=recent_days):
        return STALE
    for r in record.get("recent_runs", []):
        conclusion = r.get("conclusion")
        if not conclusion:
            continue
        if conclusion == SUCCESS:
            return PASSING
        if conclusion in FAILED_CONCLUSIONS:
            return FAILING
        if conclusion == AWAITING_CONCLUSION:
            return AWAITING
        return INCONCLUSIVE
    return INCONCLUSIVE


def scope(owner, name, tok, budget, event=None, recent_days=RECENT_DAYS,
          per_page=RECENT_RUNS, now=None):
    """One scope's activity, as ({figures}, None) or (None, reason).

    Two requests. The first carries `total_count` beside the newest page of
    runs; the second asks for the newest successful run on its own, which is
    what makes `last_success_at` exact instead of "no success inside the newest
    page". The second is skipped where the first answered zero, because no run
    at all is no successful run, and that is a certainty rather than an
    inference.
    """
    now = now or datetime.now(timezone.utc)
    label = "{}/{} {}".format(owner, name, event or "all")
    body, reason = rest(runs_path(owner, name, event=event,
                                  per_page=per_page), tok, budget, label)
    if reason:
        return None, reason
    total, runs = read_runs(body)
    if total is None:
        return None, REASON_UNANSWERED
    record = {
        "event": event,
        "runs_total": total,
        "ever_ran": total > 0,
        "runs_read": len(runs),
        "last_run_at": runs[0]["created_at"] if runs else None,
        "recent_conclusions": conclusion_counts(runs),
        "recent_runs": runs,
        "successes_total": 0 if total == 0 else None,
        "last_success_at": None,
    }
    if total:
        body, reason = rest(
            runs_path(owner, name, event=event, per_page=1, status=SUCCESS),
            tok, budget, label + " success")
        if reason:
            return None, reason
        wins, win_runs = read_runs(body)
        if wins is None:
            return None, REASON_UNANSWERED
        record["successes_total"] = wins
        record["last_success_at"] = (win_runs[0]["created_at"] if win_runs
                                     else None)
    record["status"] = derive_status(record, recent_days, now)
    return record, None


def measure(owner, name, tok, budget, recent_days=RECENT_DAYS,
            per_page=RECENT_RUNS, now=None):
    """Both scopes for one upstream, as ({record}, None) or (None, reason).

    The pull-request scope is skipped where the repository has no run of any
    kind, because pull-request runs are a subset of all runs and zero of the
    whole is zero of the part. That is recorded as `implied-by-zero-total` so
    the skipped request cannot be mistaken for an answered one.
    """
    now = now or datetime.now(timezone.utc)
    every, reason = scope(owner, name, tok, budget, event=None,
                          recent_days=recent_days, per_page=per_page, now=now)
    if reason:
        return None, reason
    if not every["ever_ran"]:
        pulls = {"event": "pull_request", "runs_total": 0, "ever_ran": False,
                 "runs_read": 0, "last_run_at": None,
                 "recent_conclusions": {}, "recent_runs": [],
                 "successes_total": 0, "last_success_at": None,
                 "status": NEVER_RAN, "source": "implied-by-zero-total"}
        return {ALL_EVENTS: every, PULL_REQUEST: pulls}, None
    pulls, reason = scope(owner, name, tok, budget, event="pull_request",
                          recent_days=recent_days, per_page=per_page, now=now)
    if reason:
        return None, reason
    return {ALL_EVENTS: every, PULL_REQUEST: pulls}, None


# ---------------------------------------------------------------- the join

def fork_upstreams(path):
    """({key: (owner, name)}, {key: reason}) from a fork_pr_profile.json.

    The names are what GitHub answered when the fork observation asked, so a
    renamed or transferred upstream is already resolved in them. The reasons
    are that run's own `not_queried`, carried over rather than re-derived:
    where it could not establish a host, neither can this.
    """
    with open(path) as fh:
        doc = json.load(fh)
    names, reasons = {}, {}
    for key, entry in (doc.get("repos") or {}).items():
        full = (entry or {}).get("name_with_owner")
        owner, _, name = str(full or "").partition("/")
        if owner and name and "/" not in name:
            names[key] = (owner, name)
    for key, reason in (doc.get("not_queried") or {}).items():
        reasons[key] = reason
    return names, reasons


# A reason the fork observation recorded that leaves the upstream's HOST
# established and only the answer missing. For those the corpus key may stand
# in as GitHub coordinates. `host-unknown` and `non-github-upstream` are
# statements about the host and are never overridden.
KEY_FALLBACK_OK = (REASON_UNANSWERED, REASON_ABSENT, REASON_BUDGET)


def pull_request_pipeline(prof):
    """{key: scope} for the repositories with a pull-request-triggered
    pipeline, which is the subset the rest of this tool quotes."""
    out = {}
    for key, entry in (prof.get("repos") or {}).items():
        pr = (entry or {}).get(PR_SCOPE) or {}
        if pr.get("primary") in ABSENT:
            continue
        out[key] = pr
    return out


def targets(prof_path, fork_path=None, upstream_path=None):
    """([target], {key: reason}).

    A target is a dict carrying the corpus key, the upstream coordinates, where
    the name came from, and whether the two names differ. Both names travel
    because a report that gave only one of them could not be checked against
    either forge.
    """
    prof, _ = read_profile(prof_path)
    mapped = read_upstreams(upstream_path) if upstream_path else {}
    answered, carried = fork_upstreams(fork_path) if fork_path else ({}, {})
    wanted, skipped = [], {}
    for key, pr in sorted(pull_request_pipeline(prof).items()):
        workflows = workflow_paths(pr)
        if not workflows:
            skipped[key] = REASON_NON_ACTIONS
            continue
        host, owner, name, origin = None, None, None, None
        if key in mapped:
            host, owner, name = mapped[key]
            origin = "upstream-file"
        if key in answered:
            # An answer beats an assertion: this name is the one GitHub gave,
            # so a rename or a transfer is already resolved in it.
            owner, name = answered[key]
            host, origin = "github.com", "fork-observation"
        if owner is None and carried.get(key) in KEY_FALLBACK_OK \
                and key.count("/") == 1:
            owner, _, name = key.partition("/")
            host, origin = "github.com", "corpus-key"
        if owner is None:
            skipped[key] = carried.get(key) or REASON_NO_UPSTREAM
            continue
        if host != "github.com":
            skipped[key] = REASON_NON_GITHUB
            continue
        wanted.append({
            "repo": key,
            "upstream": "{}/{}".format(owner, name),
            "upstream_owner": owner,
            "upstream_name": name,
            "upstream_from": origin,
            "renamed_since_mirror": "{}/{}".format(owner, name).lower()
                                    != key.lower(),
            "workflow_files": len(workflows),
            "other_grammar_files": len(pr.get("files", [])) - len(workflows),
        })
    return wanted, skipped


# ---------------------------------------------------------------- the sweep

def sweep(wanted, tok, budget, recent_days=RECENT_DAYS, now=None,
          log=print):
    """({key: record}, {key: reason}, partial_reason)."""
    now = now or datetime.now(timezone.utc)
    repos, missing, partial = {}, {}, None
    for i, target in enumerate(wanted):
        if partial:
            missing[target["repo"]] = REASON_BUDGET
            continue
        try:
            found, reason = measure(target["upstream_owner"],
                                    target["upstream_name"], tok, budget,
                                    recent_days=recent_days, now=now)
        except RateBudgetLow as e:
            partial = "stopped after {} of {} repositories: {}".format(
                i, len(wanted), e)
            log("  " + partial)
            missing[target["repo"]] = REASON_BUDGET
            continue
        if reason:
            missing[target["repo"]] = reason
            continue
        record = dict(target)
        record.update(found)
        repos[target["repo"]] = record
        if (i + 1) % 25 == 0:
            log("  {} of {} measured, {} requests spent".format(
                i + 1, len(wanted), budget.requests))
    return repos, missing, partial


# ---------------------------------------------------------------- figures

def totals(repos, skipped):
    """The distribution per scope, plus what the join cost."""
    out = {"repos_measured": len(repos), "repos_not_measured": len(skipped),
           "renamed_since_mirror": sum(
               1 for r in repos.values() if r.get("renamed_since_mirror")),
           "with_other_grammar": sum(
               1 for r in repos.values() if r.get("other_grammar_files")),
           "upstream_name_from": {}}
    for r in repos.values():
        origin = r.get("upstream_from")
        out["upstream_name_from"][origin] = \
            out["upstream_name_from"].get(origin, 0) + 1
    out["upstream_name_from"] = dict(sorted(out["upstream_name_from"].items()))
    for name in (ALL_EVENTS, PULL_REQUEST):
        counts = dict((s, 0) for s in STATUSES)
        ever = recent = runs = 0
        for r in repos.values():
            s = (r.get(name) or {}).get("status", UNKNOWN)
            counts[s] = counts.get(s, 0) + 1
            if (r.get(name) or {}).get("ever_ran"):
                ever += 1
            if s in (PASSING, FAILING, AWAITING, INCONCLUSIVE):
                recent += 1
            runs += (r.get(name) or {}).get("runs_total") or 0
        counts[UNKNOWN] = counts.get(UNKNOWN, 0) + len(skipped)
        out[name] = {"status": counts, "ever_ran": ever,
                     "ran_recently": recent,
                     "never_ran": counts[NEVER_RAN],
                     "unknown": counts[UNKNOWN],
                     "runs_recorded": runs}
    return out


def read_differential(paths):
    """[(run label, {repo: outcome})] from differential-execution outputs."""
    runs = []
    for path in paths:
        with open(path) as fh:
            doc = json.load(fh)
        outcomes = {}
        for entry in (doc.get("repositories") or []):
            if entry.get("repo"):
                outcomes[entry["repo"]] = entry.get("outcome")
        runs.append((os.path.basename(os.path.dirname(os.path.abspath(path)))
                     or os.path.basename(path),
                     doc.get("run"), outcomes))
    return runs


def control_reading(outcome, pr_status):
    """What an upstream status makes of one differential outcome.

    The pull-request-event status is the one that decides, because that is the
    event differential execution runs. A repository with push runs and no
    pull-request runs has a dead pull-request pipeline whatever else it does.
    """
    if outcome not in PROVES_NOTHING:
        return CONTROL_ANSWERED
    if pr_status == NEVER_RAN:
        return CONTROL_DEAD
    if pr_status == PASSING:
        return CONTROL_FIDELITY
    if pr_status == FAILING:
        return CONTROL_BROKEN
    if pr_status == STALE:
        return CONTROL_STALE
    return CONTROL_UNDECIDABLE


def control(repos, skipped, runs):
    """One row per repository per differential run, with its reading."""
    rows = []
    for label, when, outcomes in runs:
        for key in sorted(outcomes):
            record = repos.get(key) or {}
            pr = (record.get(PULL_REQUEST) or {})
            every = (record.get(ALL_EVENTS) or {})
            pr_status = pr.get("status", UNKNOWN)
            rows.append({
                "run": label,
                "run_date": when,
                "repo": key,
                "upstream": record.get("upstream"),
                "differential_outcome": outcomes[key],
                "upstream_status_pull_request": pr_status,
                "upstream_status_all_events": every.get("status", UNKNOWN),
                "upstream_runs_pull_request": pr.get("runs_total"),
                "upstream_runs_all_events": every.get("runs_total"),
                "upstream_last_success": pr.get("last_success_at"),
                "unknown_reason": (None if record
                                   else skipped.get(key) or REASON_NO_UPSTREAM),
                "reading": control_reading(outcomes[key], pr_status),
            })
    return rows


# ---------------------------------------------------------------- output

def write(repos, missing, budget, prof, partial_reason, path=None,
          recent_days=RECENT_DAYS, targets_asked=0, limit=None,
          prof_path=None, differential=None, measured_at=None):
    out = path or ACTIVITY_NAME
    # The files this must never land on cost hours to produce. Refused by
    # basename; see EXPERIMENTS.md, "A destructive test", for why the
    # weaker-looking comparison is the safer one.
    refuse_overwrite(out, ACTIVITY_NAME)
    stamp = measured_at or datetime.now(timezone.utc).replace(microsecond=0)
    doc = {
        "$comment": (
            "What each repository's declared CI pipeline has actually done, "
            "read from GitHub's Actions REST API. THIS IS THE UPSTREAM'S "
            "ACTIVITY: for a mirror corpus these runs happened on the host the "
            "project is developed on, not on the forge holding the mirror. "
            "Every other figure this tool produces counts configuration; this "
            "one counts runs. A repository recorded `unknown` was not "
            "measured and is never a repository whose pipeline never ran. Read "
            "`limitations` before quoting any figure."),
        "measured": stamp.date().isoformat(),
        "measured_at": stamp.isoformat(),
        "partial": bool(partial_reason),
        "partial_reason": partial_reason,
        "measures": "upstream workflow activity",
        "recent_window_days": recent_days,
        "recent_window_means": (
            "a run created within {} days of measured_at. Every figure using "
            "the words recent, passing or failing moves if this window "
            "moves.".format(recent_days)),
        "runs_read_per_scope": RECENT_RUNS,
        "status_means": STATUS_MEANS,
        "selection_rule": SELECTION_RULE,
        "scope_selected": PR_SCOPE,
        "limit": limit,
        "targets_asked": targets_asked,
        "ci_profile_source": (os.path.basename(prof_path) if prof_path
                              else None),
        "ci_profile_scanned": prof.get("scanned"),
        "ci_profile_from_cache": bool(prof.get("from_cache")),
        "rate": budget.summary(),
        "limitations": LIMITATIONS,
        "totals": totals(repos, missing),
        "repos": repos,
        # Not measured. Not one of these is a repository whose pipeline never
        # ran, and the reasons are kept apart because they call for different
        # things.
        "not_queried": missing,
        "not_queried_counts": reason_counts(missing),
    }
    if differential is not None:
        doc["control_means"] = CONTROL_MEANS
        doc["control"] = differential
    doc["output"] = out
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, out)
    return doc


def reason_counts(missing):
    counts = {}
    for reason in missing.values():
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def report(doc, log=print):
    t = doc["totals"]
    log("")
    log("=" * 72)
    log("UPSTREAM CI ACTIVITY: {}{}".format(
        doc["measured"], "  (PARTIAL RUN)" if doc["partial"] else ""))
    log("=" * 72)
    if doc["partial"]:
        log("  PARTIAL: {}".format(doc["partial_reason"]))
        log("  Every figure below is over a subset of the selected corpus.")
    log("  These runs happened UPSTREAM, on the host each project is")
    log("  developed on. For a mirror corpus they are not activity on the")
    log("  forge holding the mirror, which runs no pipeline at all.")
    log("")
    log("  targets asked                 {}".format(doc["targets_asked"]))
    log("  repositories measured         {}".format(t["repos_measured"]))
    for reason, n in doc["not_queried_counts"].items():
        log("  not measured         {:5}    {}".format(n, reason))
    log("  upstream name differs from the mirror's for {} of them".format(
        t["renamed_since_mirror"]))
    log("  name established by: {}".format(
        ", ".join("{} {}".format(v, k)
                  for k, v in t["upstream_name_from"].items())))
    log("  a second pipeline grammar beside Actions: {}".format(
        t["with_other_grammar"]))
    log("  \"recently\" means {}".format(doc["recent_window_means"]))
    for name, title in ((ALL_EVENTS, "WORKFLOW RUNS, ANY TRIGGER"),
                        (PULL_REQUEST,
                         "RUNS TRIGGERED BY A PULL REQUEST, which is the "
                         "scope quoted")):
        s = t[name]
        log("")
        log("  {}".format(title))
        log("    ever ran            {:5} of {}".format(
            s["ever_ran"], t["repos_measured"]))
        log("    ran recently        {:5}".format(s["ran_recently"]))
        log("    NEVER ran           {:5}   a declared pipeline that has done "
            "nothing".format(s["never_ran"]))
        log("    unknown             {:5}   NOT a zero".format(s["unknown"]))
        log("    runs recorded       {}".format(s["runs_recorded"]))
        for status in STATUSES:
            log("      {:18} {:5}".format(status, s["status"].get(status, 0)))
    rows = doc.get("control") or []
    if rows:
        log("")
        log("-" * 72)
        log("CONTROL FOR DIFFERENTIAL EXECUTION")
        log("-" * 72)
        log("  An environment failure on a pipeline that passes upstream is a")
        log("  fidelity gap. The same failure on a pipeline with no upstream")
        log("  runs is a dead pipeline, and reading it as a fidelity gap")
        log("  would be reading an absence as a defect.")
        for row in rows:
            log("  [{}] {}".format(row["run"], row["repo"]))
            log("      local {:20} upstream pull_request {} ({} runs)".format(
                str(row["differential_outcome"]),
                row["upstream_status_pull_request"],
                row["upstream_runs_pull_request"]))
            log("      reading: {}".format(row["reading"]))
    log("")
    log("-" * 72)
    log("WHAT THIS ESTABLISHES, AND WHAT IT DOES NOT")
    log("-" * 72)
    for line in doc["limitations"]:
        log("  - " + _wrap(line, 68, "    "))
    log("")
    rate = doc["rate"]
    log("  requests {}   budget {} of {}   remaining {}   resets {}".format(
        rate["requests"], rate["requests_this_run"], rate["limit"],
        rate["remaining"], rate["resets_at"]))
    log("  written to {}".format(doc.get("output", ACTIVITY_NAME)))


def _wrap(text, width, indent):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        lines.append(cur)
    return ("\n" + indent).join(lines)


# ---------------------------------------------------------------- entry

USAGE = ("usage: python3 -m ciprofile.ci_activity --profile=PATH "
         "[--fork=PATH] [--upstream=PATH] [--differential=PATH]... "
         "[--recent-days=N] [--limit=N] [--out=PATH]")


def parse_args(argv):
    """(profile, fork, upstream, [differential], recent_days, limit, out).

    Hand-rolled to keep every spelling of a missing value a refusal rather
    than a default, which is the shape the rest of this tool's entry points
    hold to.
    """
    paths = {"profile": None, "fork": None, "upstream": None}
    differential, recent, limit, out = [], RECENT_DAYS, None, None

    def existing(flag, value):
        if not value:
            raise SystemExit("--{} needs a path".format(flag))
        if not os.path.exists(value):
            raise SystemExit("--{}: no such file {}".format(flag, value))
        return value

    for arg in argv:
        m = re.fullmatch(r"--(profile|fork|upstream)(?:=(.+))?", arg)
        if m:
            paths[m.group(1)] = existing(m.group(1), m.group(2))
            continue
        m = re.fullmatch(r"--differential(?:=(.+))?", arg)
        if m:
            differential.append(existing("differential", m.group(1)))
            continue
        m = re.fullmatch(r"--recent-days(?:=(\d+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit(
                    "--recent-days needs a number: --recent-days=30")
            recent = int(m.group(1))
            if recent < 1:
                raise SystemExit("--recent-days must be at least 1")
            continue
        m = re.fullmatch(r"--limit(?:=(\d+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--limit needs a number: --limit=50")
            limit = int(m.group(1))
            continue
        m = re.fullmatch(r"--out(?:=(.+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--out needs a path")
            out = m.group(1)
            continue
        raise SystemExit("unknown argument {!r}. {}".format(arg, USAGE))
    return (paths["profile"], paths["fork"], paths["upstream"], differential,
            recent, limit, out)


def main(argv=None):
    (prof_path, fork_path, upstream_path, diff_paths, recent, limit,
     out) = parse_args(list(argv if argv is not None else sys.argv[1:]))
    if prof_path is None:
        raise SystemExit(
            "--profile is required: it defines the corpus and which "
            "repositories declare a pull-request-triggered pipeline. " + USAGE)
    if fork_path is None and upstream_path is None:
        raise SystemExit(
            "one of --fork or --upstream is required: the upstream's name "
            "cannot be guessed from a mirror's, and a corpus of mirrors holds "
            "upstreams that have been renamed or transferred since. " + USAGE)
    tok = token()
    wanted, missing = targets(prof_path, fork_path, upstream_path)
    asked = len(wanted)
    if limit is not None:
        for target in wanted[limit:]:
            missing[target["repo"]] = REASON_LIMIT
        wanted = wanted[:limit]
        asked = len(wanted)
    prof, _ = read_profile(prof_path)
    print("ci_activity: {} upstreams with a pull-request-triggered pipeline, "
          "recency window {} days".format(asked, recent))
    print("  upstream names from {}".format(
        ", ".join(p for p in (fork_path, upstream_path) if p)))
    for reason, n in reason_counts(missing).items():
        print("  {} not measured: {}".format(n, reason))
    budget = RestBudget()
    repos, gone, partial = sweep(wanted, tok, budget, recent_days=recent)
    missing.update(gone)
    rows = control(repos, missing, read_differential(diff_paths)) \
        if diff_paths else None
    doc = write(repos, missing, budget, prof, partial,
                path=out or os.path.join(os.path.dirname(prof_path) or ".",
                                         ACTIVITY_NAME),
                recent_days=recent, targets_asked=asked, limit=limit,
                prof_path=prof_path, differential=rows)
    report(doc)
    return doc


if __name__ == "__main__":
    main()
