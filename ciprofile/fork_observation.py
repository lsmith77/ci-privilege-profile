#!/usr/bin/env python3
"""Observation instead of inference: what CI actually did on fork pull requests.

    GITHUB_TOKEN=... python3 -m ciprofile.fork_observation \
        --profile data/ci_profile.json [--limit N] [--cap N]

Writes fork_pr_profile.json. Reads GitHub and nothing else.

WHY THIS IS NOT ANOTHER INFERENCE
---------------------------------
The classifier answers "would this pipeline run on a contributor's own
infrastructure" by reading the pipeline text and reasoning about what it asks
for. That is inference, and it cannot check itself.

GitHub performs the experiment on every fork pull request. Its documentation
states the rule in both directions: "With the exception of GITHUB_TOKEN,
secrets are not passed to the runner when a workflow is triggered from a forked
repository", and "The GITHUB_TOKEN has read-only permissions in pull requests
from forked repositories".¹ The three organisation policies that lift either
half ("Run workflows from fork pull requests", "Send write tokens to workflows
from pull requests", "Send secrets to workflows from pull requests") are
"Available to private repositories only".² For a public repository, therefore,
no setting can have turned the withholding off.

Therefore: **a workflow that has passed on a fork pull request ran with no
repository secret and a read-only forge token.** That is observable, per
repository, and it is evidence about the classifier that the classifier cannot
produce about itself.

The asymmetry is total, and every figure printed says so:

  - a PASS proves the pipeline needs no repository secret;
  - a FAILURE proves nothing, because the change itself may be what failed.

So this measures a floor, never a ceiling, and a repository with no passing
fork pull request is not thereby a repository that needs one.

¹ https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
² https://docs.github.com/en/organizations/managing-organization-settings/disabling-or-limiting-github-actions-for-your-organization

THE PRIOR QUESTION, WHICH MAY BE THE WHOLE FINDING
--------------------------------------------------
The proof above needs fork pull requests to exist. Whether a given corpus
receives external contribution at all is measured here first, ahead of any CI
figure: total pull requests, how many came from a fork, and how many of those
came from a fork someone else owns. If fork contribution is near zero then the
question this tool exists to answer is theoretical for that corpus until
contribution exists, which makes it an argument about participation, not about
runners. That absence is a finding, not a failed measurement, and the report
leads with it either way. In the corpus this method was built against (public
repositories published by organisations rather than by software vendors), the
absence is exactly what it found.

THREE FIELDS, AND WHAT EACH ONE REALLY SAYS
-------------------------------------------
Read off GitHub's published GraphQL schema rather than assumed.

`PullRequest.isCrossRepository: Boolean!` is documented as "The head and base
repositories are different." Non-nullable, so there is no third state to
mishandle. It is the right predicate for the *secrets* question, because
GitHub withholds on exactly this condition, whoever owns the fork. It is the
wrong predicate for the *contribution* question: an in-house fork-and-PR
workflow sets it too. So `headRepositoryOwner.login` is collected beside it
and the two counts are reported separately.

`Commit.statusCheckRollup: StatusCheckRollup` is nullable, and
`StatusCheckRollup.state: StatusState!` is one of ERROR, EXPECTED, FAILURE,
PENDING, SUCCESS. The nullability is the whole reason this is not a boolean:

  - rollup null                -> `no-checks`. Nothing was attached to that
                                  commit. Distinct from a failure and never
                                  merged into one: a repository whose fork
                                  pull requests were never checked has not
                                  told us its pipeline fails, and GitHub's own
                                  "require approval for first-time
                                  contributors" produces exactly this.
  - the commit itself missing  -> `head-unavailable`. A deleted fork can leave
                                  the head commit unreachable, which is a gap
                                  in the evidence, not a result.
  - SUCCESS                    -> `passed`
  - FAILURE / ERROR            -> `failed`
  - PENDING / EXPECTED         -> `pending`

The rollup is taken from `commits(last: 1)`, the last commit *in the pull
request*, and the oid is recorded, so the result is anchored to a named commit.
`PullRequest.statusCheckRollup` is collected alongside at no node cost; it is
documented as the rollup "for the PR's head ref", which for a merged or closed
pull request can have moved on. Disagreements between the two are counted
rather than resolved silently.

WHY A PASS IS NOT TAKEN AT FACE VALUE
-------------------------------------
Two things make a green rollup worthless as proof, both invisible in the state
alone. Both were found while building this, and either would have produced a
flattering wrong answer:

  - **`pull_request_target`.** That event runs the workflow in the *base*
    repository's context, with secrets and a write token. A green run from it
    says nothing about secret independence. `WorkflowRun.event` is what
    distinguishes it, and it is read for every check.
  - **Checks that are not Actions.** `StatusCheckRollup` spans "status
    contexts and check runs", so a third-party CI app posting a commit status
    counts toward SUCCESS, and that provider's secret model is its own, not
    GitHub's. The app slug and the workflow name are recorded, and a pass
    backed by nothing but foreign statuses is reported as unproven.

A repository is called `secret-free-proven` only where some passing fork pull
request carries an Actions check run whose own workflow run was triggered by
`pull_request`. Everything softer is `passed-unproven`, with the reason
attached.

BOUNDING THE WORK, AND SAYING SO IN THE FILE
--------------------------------------------
At most CAP pull requests are examined per repository, newest first by creation
time. Every count is therefore **censored from below** for a capped
repository: it saw the newest CAP, and an older fork pull request it did not
reach cannot be ruled out. The cap travels in the JSON and `capped: true` is
set per repository where it bit, because the terminal summary scrolls away.

Newest-first is the deliberate bias: the question is whether these projects
receive external contribution, which is a question about the present.

THREE PASSES, CHEAPEST FIRST
----------------------------
GraphQL is billed on requested nodes, so the shape of the sweep is the cost
control. A per-repository REST loop would be two orders of magnitude more
requests.

  1. **screen**: `pullRequests { totalCount }` for every target, batched
     SCREEN_BATCH at a time. No connection elements are requested, so each
     call costs the one-point minimum, and it removes every repository with no
     pull requests at all from the expensive pass.
  2. **sample**: for the remainder, the newest CAP pull requests with
     `isCrossRepository` and the head commit's rollup. ~2*CAP nodes per
     repository, so the batch is small: the node count drives both the price
     and the chance of a server-side timeout.
  3. **evidence**: only the pull requests that passed, re-queried for their
     rollup contexts. Small by construction, and it is what turns "green" into
     "green, from an Actions run triggered by pull_request".

`rateLimit` rides on every query (it is free) and the budget is read from the
API rather than guessed. When `remaining` falls below RATE_FLOOR the sweep
stops, writes what it has, marks the file `partial`, and records every
unreached repository as `rate-budget-exhausted`, never as "no fork pull
requests". Here the flattering mistake would be to read an unasked repository
as a quiet one.

THE TARGET SET
--------------
The corpus is the profile's own repository keys, so this validates the classes
that profile assigned and no others. Where those keys are GitHub coordinates
(a profile produced by the github source), they are used directly. Otherwise
the upstream host has to be written down somewhere, because it cannot be
guessed from a repository's name: `--upstream FILE` maps
`corpus-key owner/name` per line. A key with no mapping is recorded
`host-unknown` and a mapping to another host `non-github-upstream`. Both are
in `not_queried`, and neither is counted as a repository without fork pull
requests.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

from .classify import PR_SCOPE
from .report import FORK_NAME, refuse_overwrite

GRAPHQL = "https://api.github.com/graphql"
ATTEMPTS = 3
# Scalars only, no connection elements, so eighty repositories cost one point.
SCREEN_BATCH = 80
# An order of magnitude smaller, because each repository here brings ~2*CAP
# nodes. Ten at CAP=100 is ~2000 nodes a call: cheap in points and small
# enough that the server answers it without timing out, which a batch of eighty
# would not.
SAMPLE_BATCH = 10
EVIDENCE_BATCH = 20
# Rollup contexts read per passing pull request. A pull request with more
# checks than this has its context list truncated, which is recorded; the proof
# needs only one qualifying Actions run, so truncation can lose corroboration
# but cannot manufacture it.
CONTEXTS = 20
DEFAULT_CAP = 100

# Stop with this many points still in hand. A sample call costs about twenty,
# so this leaves room to finish the batch in flight, run the evidence pass over
# what was found, and write the file.
RATE_FLOOR = int(os.environ.get("FORK_RATE_FLOOR", "250"))
# Gap between requests. The floor cannot be configured away, for the reason the
# source adapters give: a knob that can be set to zero is a knob that will be.
PACE_FLOOR = 0.5


def pace_seconds(asked=None):
    if asked is None:
        asked = os.environ.get("FORK_PACE_SECONDS")
    try:
        want = float(asked)
    except (TypeError, ValueError):
        return PACE_FLOOR
    return want if want > PACE_FLOOR else PACE_FLOOR


PACE_SECONDS = pace_seconds()

# Outcome buckets. "no-checks" and "failed" are different findings and are
# never merged.
PASSED = "passed"
FAILED = "failed"
PENDING = "pending"
NO_CHECKS = "no-checks"
HEAD_UNAVAILABLE = "head-unavailable"
BUCKETS = [PASSED, FAILED, PENDING, NO_CHECKS, HEAD_UNAVAILABLE]

# Why a target was not asked about. Each is its own reason because they call
# for different things: one is a gap in the corpus's own metadata, one is out
# of scope by design, one is a run that should be repeated, one is an upstream
# that has gone away.
REASON_HOST_UNKNOWN = "host-unknown"
REASON_NON_GITHUB = "non-github-upstream"
REASON_BUDGET = "rate-budget-exhausted"
REASON_UNANSWERED = "query-unanswered"
REASON_ABSENT = "upstream-absent"
REASON_LIMIT = "beyond-limit"

PROVEN = "secret-free-proven"
UNPROVEN = "passed-unproven"

# The classifier's classes this measurement can contradict: a fork pull request
# that passed on a repository the classifier called privileged is a repository
# whose privilege was droppable.
PRIVILEGED_CLASSES = ["acts-on-forge", "writes-outward", "read-credential",
                      "special-env"]

LIMITATIONS = [
    "A PASSING fork pull request proves the pipeline ran with no repository "
    "secret and a read-only forge token, because GitHub withholds both from "
    "fork pull requests and the override is private-repositories-only. A "
    "FAILING one proves NOTHING on its own: the change itself may be what "
    "failed.",
    "This is a floor, never a ceiling. A repository with no passing fork pull "
    "request is not a repository that needs a secret; most likely it simply "
    "has no fork pull requests.",
    "Counts are CENSORED for any repository marked `capped`: only the newest "
    "`cap` pull requests were examined, so an older fork pull request cannot "
    "be ruled out.",
    "`fork_prs` counts isCrossRepository, which an in-house fork-and-PR "
    "workflow also sets. The contribution figure to quote is the count of fork "
    "pull requests whose head fork has a DIFFERENT owner.",
    "A null statusCheckRollup is `no-checks`, not a failure. GitHub's approval "
    "gate for first-time contributors produces exactly this.",
    "The rollup spans third-party commit statuses as well as Actions check "
    "runs, and a `pull_request_target` run holds secrets. Only a pass carrying "
    "an Actions check run from a `pull_request`-triggered workflow run is "
    "counted as proof; the rest are `passed-unproven`.",
    "Repositories in `not_queried` were not measured. None of them is a "
    "repository without fork pull requests.",
    "The method only works where fork contributions exist. Where they do not, "
    "that absence is the finding, and it validates nothing about the "
    "classifier either way.",
]


# ---------------------------------------------------------------- transport

def token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        raise SystemExit(
            "GITHUB_TOKEN is not set: this needs a GitHub token (no scopes "
            "required; every repository queried is public)")
    return tok


class RateBudgetLow(Exception):
    """Raised instead of making a call that would run the budget down."""


class Budget:
    """The rate limit as the API reports it, not as we guess at it."""

    def __init__(self, floor=None):
        self.floor = RATE_FLOOR if floor is None else floor
        self.limit = None
        self.remaining = None
        self.reset_at = None
        self.used = None
        self.cost = 0            # points this run has spent, per the API
        self.requests = 0
        self.node_count = 0

    def observe(self, rl):
        if not rl:
            return
        for key, attr in (("limit", "limit"), ("remaining", "remaining"),
                          ("used", "used"), ("resetAt", "reset_at")):
            if rl.get(key) is not None:
                setattr(self, attr, rl[key])
        if rl.get("cost") is not None:
            self.cost += rl["cost"]
        if rl.get("nodeCount") is not None:
            self.node_count += rl["nodeCount"]

    def low(self):
        return self.remaining is not None and self.remaining < self.floor

    def check(self):
        if self.low():
            raise RateBudgetLow(
                "{} of {} points left (floor {}), resets at {}".format(
                    self.remaining, self.limit, self.floor, self.reset_at))

    def summary(self):
        return {"limit": self.limit, "remaining": self.remaining,
                "used_by_api_count": self.used, "spent_this_run": self.cost,
                "node_count_this_run": self.node_count,
                "resets_at": self.reset_at, "requests": self.requests,
                "floor": self.floor}


# The one HTTP call site. Stubbed wholesale by the offline tests, which also
# take the socket layer away, so a stub that fell through would fail rather
# than reach GitHub.
def post(query, tok, timeout=120):
    req = urllib.request.Request(GRAPHQL, method="POST",
                                 data=json.dumps({"query": query}).encode())
    req.add_header("Authorization", "bearer " + tok)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


RATE_FRAGMENT = "rateLimit { limit cost remaining resetAt used nodeCount }"


def graphql(query, tok, budget, label=""):
    """Pace, post, bank the rate limit. Returns the data dict, or None.

    None means "this batch was not answered": every repository in it is
    `query-unanswered`, never a repository with no fork pull requests.
    RateBudgetLow is raised *before* a call rather than after, so the caller
    stops with a budget still large enough to write its results.
    """
    budget.check()
    for attempt in range(1, ATTEMPTS + 1):
        if budget.requests:
            time.sleep(PACE_SECONDS)
        budget.requests += 1
        try:
            body = post(query, tok)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit(
                    "GitHub rejected the token (HTTP 401). Nothing was "
                    "measured. Fix the credential rather than re-running.")
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
        budget.observe(body.get("data", {}).get("rateLimit")
                       if isinstance(body.get("data"), dict) else None)
        if not body.get("data"):
            # Falsy, not absent: a primary rate-limit refusal answers
            # {"data": null, "errors": [...]}, and a `"data" not in body` guard
            # would hand that back as a success.
            print("  {} attempt {} rejected: {}".format(
                label, attempt, str(body.get("errors"))[:200]),
                file=sys.stderr)
            time.sleep(5 * attempt)
            continue
        return body["data"]
    return None


def q_str(s):
    """GitHub restricts owner/repo names to [A-Za-z0-9._-], but these names
    come from somebody else's dataset, so escape rather than trust that."""
    return json.dumps(str(s))


# ---------------------------------------------------------------- targets

def read_upstreams(path):
    """{corpus key: (host, owner, name)} from a mapping file.

    `corpus-key owner/name` or `corpus-key https://host/owner/name` per line.
    The host cannot be guessed from a repository's name, so it is written down
    or the repository is not asked about.
    """
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise SystemExit(
                    "{}: {!r} is not `corpus-key upstream`".format(path, line))
            key, up = parts
            if up.endswith(".git"):
                up = up[:-4]
            if "://" in up:
                bits = up.split("/")
                if len(bits) < 5:
                    raise SystemExit("{}: cannot read {!r}".format(path, up))
                out[key] = (bits[2], bits[3], bits[-1])
            else:
                owner, _, name = up.partition("/")
                if not name:
                    raise SystemExit(
                        "{}: {!r} is not owner/name".format(path, up))
                out[key] = ("github.com", owner, name)
    return out


def read_profile(path):
    """(profile, [every repository it covers, classified or unknown])."""
    with open(path) as fh:
        prof = json.load(fh)
    return prof, sorted(set(prof.get("repos", {}))
                        | set(prof.get("unknown", {})))


def targets(prof_path, upstream_path=None):
    """([(key, owner, name)] on GitHub, {key: reason} for the rest)."""
    prof, keys = read_profile(prof_path)
    mapping = read_upstreams(upstream_path) if upstream_path else {}
    native = (prof.get("source") or {}).get("source") == "github"
    github, skipped = [], {}
    for key in keys:
        found = mapping.get(key)
        if found is None and native and key.count("/") == 1:
            # The profile's own keys are GitHub coordinates, because the github
            # source produced it. Nothing to map.
            owner, _, name = key.partition("/")
            github.append((key, owner, name))
            continue
        if found is None:
            skipped[key] = REASON_HOST_UNKNOWN
            continue
        host, owner, name = found
        if host != "github.com":
            skipped[key] = REASON_NON_GITHUB
            continue
        github.append((key, owner, name))
    return github, skipped


# ---------------------------------------------------------------- pass 1

def screen_query(chunk):
    body = "".join(
        "  r{}: repository(owner: {}, name: {}) {{\n"
        "    nameWithOwner isArchived\n"
        "    pullRequests {{ totalCount }}\n"
        "  }}\n".format(i, q_str(o), q_str(n))
        for i, (_, o, n) in enumerate(chunk))
    return "query {\n" + body + "  " + RATE_FRAGMENT + "\n}"


def screen(chunk, tok, budget):
    """{key: {name_with_owner, archived, prs_total}} plus {key: reason}."""
    data = graphql(screen_query(chunk), tok, budget, "screen")
    found, missing = {}, {}
    for i, (key, _o, _n) in enumerate(chunk):
        if data is None:
            missing[key] = REASON_UNANSWERED
            continue
        node = data.get("r{}".format(i))
        if node is None:
            missing[key] = REASON_ABSENT
            continue
        found[key] = {
            "name_with_owner": node.get("nameWithOwner"),
            "archived": bool(node.get("isArchived")),
            "prs_total": (node.get("pullRequests") or {}).get("totalCount"),
        }
    return found, missing


# ---------------------------------------------------------------- pass 2

PR_FIELDS = """
      number state createdAt isCrossRepository
      headRepositoryOwner { login }
      author { login }
      statusCheckRollup { state }
      commits(last: 1) { totalCount nodes { commit { oid statusCheckRollup { state } } } }
"""


def sample_query(chunk, cap):
    body = "".join(
        "  r{}: repository(owner: {}, name: {}) {{\n"
        "    nameWithOwner\n"
        "    pullRequests(first: {}, "
        "orderBy: {{field: CREATED_AT, direction: DESC}}) {{\n"
        "      totalCount\n"
        "      nodes {{{}      }}\n"
        "    }}\n"
        "  }}\n".format(i, q_str(o), q_str(n), int(cap), PR_FIELDS)
        for i, (_, o, n) in enumerate(chunk))
    return "query {\n" + body + "  " + RATE_FRAGMENT + "\n}"


def head_commit(pr):
    """The last commit in the pull request, or None if it is unreachable.

    A deleted fork can leave it so; that is a gap in the evidence, which must
    not read as a result.
    """
    nodes = ((pr.get("commits") or {}).get("nodes") or [])
    for node in nodes:
        if node and node.get("commit"):
            return node["commit"]
    return None


def outcome(pr):
    """(bucket, rollup state or None, oid or None). See THREE FIELDS."""
    commit = head_commit(pr)
    if commit is None:
        return HEAD_UNAVAILABLE, None, None
    oid = commit.get("oid")
    rollup = commit.get("statusCheckRollup")
    if rollup is None:
        # Nothing was attached to this commit. Not a failure, and never
        # recorded as one.
        return NO_CHECKS, None, oid
    state = rollup.get("state")
    if state == "SUCCESS":
        return PASSED, state, oid
    if state in ("FAILURE", "ERROR"):
        return FAILED, state, oid
    if state in ("PENDING", "EXPECTED"):
        return PENDING, state, oid
    # An enum value the schema did not have when this was written. Unknown is
    # not a pass and is not a failure.
    return (NO_CHECKS if state is None else PENDING), state, oid


def fork_record(pr, repo_owner):
    bucket, state, oid = outcome(pr)
    head_owner = (pr.get("headRepositoryOwner") or {}).get("login")
    author = (pr.get("author") or {}).get("login")
    pr_rollup = (pr.get("statusCheckRollup") or {}).get("state")
    return {
        "number": pr.get("number"),
        "state": pr.get("state"),
        "created": pr.get("createdAt"),
        "head_owner": head_owner,
        # The contribution predicate, as against isCrossRepository's CI
        # predicate. An unknown head owner is not read as "same owner".
        "external_owner": bool(head_owner
                               and head_owner.lower() != repo_owner.lower()),
        "author": author,
        "outcome": bucket,
        "rollup_state": state,
        # The PR-level rollup, free to collect and documented against the head
        # *ref* rather than this commit. Kept to be compared, not merged.
        "pr_rollup_state": pr_rollup,
        "head_oid": oid,
    }


def sample(chunk, tok, budget, cap, screened):
    """{key: entry} for the repositories answered, {key: reason} for the rest."""
    data = graphql(sample_query(chunk, cap), tok, budget, "sample")
    out, missing = {}, {}
    for i, (key, owner, _n) in enumerate(chunk):
        if data is None:
            missing[key] = REASON_UNANSWERED
            continue
        node = data.get("r{}".format(i))
        if node is None:
            missing[key] = REASON_ABSENT
            continue
        conn = node.get("pullRequests") or {}
        prs = [p for p in (conn.get("nodes") or []) if p]
        total = conn.get("totalCount")
        if total is None:
            total = (screened.get(key) or {}).get("prs_total")
        forks = [fork_record(p, owner) for p in prs
                 if p.get("isCrossRepository")]
        counts = {b: 0 for b in BUCKETS}
        for f in forks:
            counts[f["outcome"]] = counts.get(f["outcome"], 0) + 1
        base = dict(screened.get(key) or {})
        base.update({
            "name_with_owner": node.get("nameWithOwner")
                               or base.get("name_with_owner"),
            "prs_total": total,
            "prs_examined": len(prs),
            # Censored from below where this is true: an older fork pull
            # request outside the window cannot be ruled out.
            "capped": bool(total is not None and total > len(prs)),
            "fork_prs": len(forks),
            "fork_prs_external_owner": sum(1 for f in forks
                                           if f["external_owner"]),
            "outcomes": counts,
            "rollup_disagreements": sum(
                1 for f in forks
                if f["pr_rollup_state"] is not None
                and f["rollup_state"] is not None
                and f["pr_rollup_state"] != f["rollup_state"]),
            "fork_pr_detail": forks,
        })
        out[key] = base
    return out, missing


# ---------------------------------------------------------------- pass 3

CONTEXT_FIELDS = """
          __typename
          ... on CheckRun {
            name conclusion status
            checkSuite { app { slug } workflowRun { event workflow { name } } }
          }
          ... on StatusContext { context state creator { login } }
"""


def evidence_query(pairs, contexts=CONTEXTS):
    """pairs: [(key, owner, name, number)] -> one aliased query."""
    body = "".join(
        "  p{}: repository(owner: {}, name: {}) {{\n"
        "    pullRequest(number: {}) {{\n"
        "      number\n"
        "      commits(last: 1) {{ nodes {{ commit {{ oid\n"
        "        statusCheckRollup {{ state contexts(first: {}) "
        "{{ totalCount nodes {{{}        }} }} }}\n"
        "      }} }} }}\n"
        "    }}\n"
        "  }}\n".format(i, q_str(o), q_str(n), int(num), int(contexts),
                        CONTEXT_FIELDS)
        for i, (_k, o, n, num) in enumerate(pairs))
    return "query {\n" + body + "  " + RATE_FRAGMENT + "\n}"


def read_contexts(pr):
    """([check dicts], truncated, rollup state) for one pull request node."""
    commit = head_commit(pr or {})
    rollup = (commit or {}).get("statusCheckRollup") or {}
    conn = rollup.get("contexts") or {}
    nodes = [c for c in (conn.get("nodes") or []) if c]
    checks = []
    for c in nodes:
        if c.get("__typename") == "CheckRun":
            suite = c.get("checkSuite") or {}
            run = suite.get("workflowRun") or {}
            checks.append({
                "kind": "check-run",
                "name": c.get("name"),
                "conclusion": c.get("conclusion"),
                "status": c.get("status"),
                "app": (suite.get("app") or {}).get("slug"),
                "workflow": (run.get("workflow") or {}).get("name"),
                # The field the whole proof turns on: a pull_request_target run
                # holds the repository's secrets.
                "event": run.get("event"),
            })
        else:
            checks.append({
                "kind": "status",
                "name": c.get("context"),
                "conclusion": c.get("state"),
                "app": None,
                "workflow": None,
                "event": None,
                "creator": (c.get("creator") or {}).get("login"),
            })
    total = conn.get("totalCount")
    truncated = bool(total is not None and total > len(nodes))
    return checks, truncated, rollup.get("state")


def judge(checks):
    """(verdict, reason) for one passing fork pull request's checks.

    PROVEN needs a successful Actions check run whose own workflow run was
    triggered by `pull_request`. Nothing softer counts.
    """
    qualifying = [c for c in checks
                  if c["kind"] == "check-run"
                  and c.get("event") == "pull_request"
                  and c.get("conclusion") == "SUCCESS"]
    if qualifying:
        return PROVEN, None
    if not checks:
        return UNPROVEN, "no check detail returned"
    if any(c.get("event") == "pull_request_target" for c in checks):
        return UNPROVEN, ("the green run was pull_request_target, which runs "
                          "with the base repository's secrets")
    runs = [c for c in checks if c["kind"] == "check-run"]
    if not runs:
        who = sorted({c.get("creator") or c.get("name") or "?"
                      for c in checks})
        return UNPROVEN, ("green from commit statuses only, posted by "
                          + ", ".join(who) + " (not an Actions run)")
    events = sorted({c.get("event") or "unknown" for c in runs})
    concl = sorted({c.get("conclusion") or "unknown" for c in runs})
    return UNPROVEN, ("Actions runs present but none is a successful "
                      "pull_request run (events {}, conclusions {})".format(
                          events, concl))


def evidence(repos, tok, budget):
    """Fill in check detail for every passing fork pull request, in place.

    Returns how many pull requests it managed to look at. Stops at the budget
    like every other pass, leaving the rest with no detail, which `judge` then
    reads as unproven, the under-claiming direction.
    """
    pairs = []
    for key, entry in sorted(repos.items()):
        owner, _, name = key.partition("/")
        for f in entry.get("fork_pr_detail", []):
            if f["outcome"] == PASSED and f.get("number") is not None:
                pairs.append((key, owner, name, f["number"]))
    looked = 0
    for start in range(0, len(pairs), EVIDENCE_BATCH):
        batch = pairs[start:start + EVIDENCE_BATCH]
        try:
            data = graphql(evidence_query(batch), tok, budget, "evidence")
        except RateBudgetLow:
            break
        if data is None:
            continue
        for i, (key, _o, _n, num) in enumerate(batch):
            node = data.get("p{}".format(i)) or {}
            pr = node.get("pullRequest")
            if pr is None:
                continue
            checks, truncated, state = read_contexts(pr)
            verdict, reason = judge(checks)
            for f in repos[key]["fork_pr_detail"]:
                if f["number"] == num:
                    f["checks"] = checks
                    f["checks_truncated"] = truncated
                    f["rollup_state_recheck"] = state
                    f["verdict"] = verdict
                    f["verdict_reason"] = reason
                    looked += 1
    for entry in repos.values():
        passing = [f for f in entry.get("fork_pr_detail", [])
                   if f["outcome"] == PASSED]
        if not passing:
            continue
        entry["proof"] = (PROVEN
                          if any(f.get("verdict") == PROVEN for f in passing)
                          else UNPROVEN)
    return looked


# ---------------------------------------------------------------- the sweep

def sweep(github, tok, budget, cap=DEFAULT_CAP):
    """(repos, not_queried, partial_reason)."""
    repos, missing, partial_reason = {}, {}, None
    screened = {}
    i = 0
    try:
        for start in range(0, len(github), SCREEN_BATCH):
            chunk = github[start:start + SCREEN_BATCH]
            found, gone = screen(chunk, tok, budget)
            screened.update(found)
            missing.update(gone)
            i = start + len(chunk)
            print("  screened {}/{} (remaining {})".format(
                i, len(github), budget.remaining))
    except RateBudgetLow as e:
        partial_reason = "screen pass stopped: {}".format(e)
    for key, _o, _n in github[i:]:
        if key not in screened and key not in missing:
            missing[key] = REASON_BUDGET

    # Every screened repository is recorded, whether or not the sample pass
    # reaches it: a repository with no pull requests at all is an answer, and
    # one the sample pass could not reach is not.
    for key, base in screened.items():
        repos[key] = dict(base, prs_examined=0, capped=False, fork_prs=0,
                          fork_prs_external_owner=0,
                          outcomes={b: 0 for b in BUCKETS},
                          rollup_disagreements=0, fork_pr_detail=[])

    todo = [(k, o, n) for k, o, n in github
            if (screened.get(k) or {}).get("prs_total")]
    print("  {} of {} screened repositories have at least one pull request"
          .format(len(todo), len(screened)))
    done = 0
    if partial_reason is None:
        try:
            for start in range(0, len(todo), SAMPLE_BATCH):
                chunk = todo[start:start + SAMPLE_BATCH]
                got, gone = sample(chunk, tok, budget, cap, screened)
                repos.update(got)
                for key in gone:
                    repos.pop(key, None)
                missing.update(gone)
                done = start + len(chunk)
                if done % (SAMPLE_BATCH * 10) == 0 or done == len(todo):
                    print("  sampled {}/{} (remaining {})".format(
                        done, len(todo), budget.remaining))
        except RateBudgetLow as e:
            partial_reason = "sample pass stopped: {}".format(e)
    for key, _o, _n in todo[done:]:
        repos.pop(key, None)
        missing[key] = REASON_BUDGET

    looked = evidence(repos, tok, budget)
    print("  evidence pass looked at {} passing fork pull requests"
          .format(looked))
    return repos, missing, partial_reason


# ---------------------------------------------------------------- the join

def classes(prof, key):
    """(primary, credentials axis flag or None) in the pull-request scope."""
    entry = (prof.get("repos") or {}).get(key)
    if not entry:
        return ("unknown" if key in (prof.get("unknown") or {})
                else "not-profiled"), None
    scope = entry.get(PR_SCOPE) or {}
    axis = next((f for f in scope.get("flags", [])
                 if f.startswith("credentials-")), None)
    return scope.get("primary"), axis


def validation(repos, prof):
    """One row per repository with a passing fork pull request."""
    rows = []
    for key, entry in sorted(repos.items()):
        passing = [f for f in entry.get("fork_pr_detail", [])
                   if f["outcome"] == PASSED]
        if not passing:
            continue
        primary, axis = classes(prof, key)
        rows.append({
            "repo": key,
            "ci_class_pull_request": primary,
            "ci_credentials_axis": axis,
            "contradicts_classifier": primary in PRIVILEGED_CLASSES,
            "proof": entry.get("proof", UNPROVEN),
            "passing_fork_prs": [
                {"number": f["number"],
                 "url": "https://github.com/{}/pull/{}".format(key,
                                                               f["number"]),
                 "head_owner": f["head_owner"],
                 "external_owner": f["external_owner"],
                 "verdict": f.get("verdict", UNPROVEN),
                 "reason": f.get("verdict_reason"),
                 "checks": [c["name"] for c in f.get("checks", [])],
                 "events": sorted({c["event"] for c in f.get("checks", [])
                                   if c.get("event")}),
                 } for f in passing],
        })
    # The contradictions first, then the proven ones: the reader is here for
    # the rows that disagree with the classifier.
    rows.sort(key=lambda r: (not r["contradicts_classifier"],
                             r["proof"] != PROVEN, r["repo"]))
    return rows


def totals(repos):
    t = {"repos_measured": len(repos), "prs_total": 0, "fork_prs": 0,
         "fork_prs_external_owner": 0,
         "repos_with_any_pr": 0, "repos_with_fork_pr": 0,
         "repos_with_external_fork_pr": 0, "repos_capped": 0,
         "repos_with_passing_fork_pr": 0, "repos_proven": 0,
         "rollup_disagreements": 0,
         "fork_pr_outcomes": {b: 0 for b in BUCKETS}}
    for entry in repos.values():
        t["prs_total"] += entry.get("prs_total") or 0
        t["fork_prs"] += entry.get("fork_prs") or 0
        t["fork_prs_external_owner"] += entry.get(
            "fork_prs_external_owner") or 0
        t["rollup_disagreements"] += entry.get("rollup_disagreements") or 0
        if entry.get("prs_total"):
            t["repos_with_any_pr"] += 1
        if entry.get("fork_prs"):
            t["repos_with_fork_pr"] += 1
        if entry.get("fork_prs_external_owner"):
            t["repos_with_external_fork_pr"] += 1
        if entry.get("capped"):
            t["repos_capped"] += 1
        for b, n in (entry.get("outcomes") or {}).items():
            t["fork_pr_outcomes"][b] = t["fork_pr_outcomes"].get(b, 0) + n
        if (entry.get("outcomes") or {}).get(PASSED):
            t["repos_with_passing_fork_pr"] += 1
        if entry.get("proof") == PROVEN:
            t["repos_proven"] += 1
    return t


# ---------------------------------------------------------------- output

def write(repos, missing, budget, cap, prof, partial_reason, path=None,
          targets_asked=0, limit=None, prof_path=None):
    out = path or FORK_NAME
    # The files this must never land on cost hours to produce. Refused by
    # basename; see EXPERIMENTS.md, "A destructive test", for why the
    # weaker-looking comparison is the safer one.
    refuse_overwrite(out, FORK_NAME)
    doc = {
        "$comment": (
            "Fork-based contribution to a corpus and the CI outcome on it, "
            "read from GitHub's GraphQL API. A PASSING fork pull request "
            "proves the pipeline ran with no repository secret and a read-only "
            "forge token, because GitHub withholds both from fork pull "
            "requests and the override is private-repositories-only. A FAILING "
            "one proves nothing. Read `limitations` before quoting any "
            "figure."),
        "measured": date.today().isoformat(),
        "measured_at": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "partial": bool(partial_reason),
        "partial_reason": partial_reason,
        "cap_per_repo": cap,
        "cap_order": "newest first by createdAt",
        "limit": limit,
        "targets_asked": targets_asked,
        # Which profile the validation table was joined against. The table is
        # unreadable without it: a class only means something alongside the
        # reading that assigned it, and this tool produces more than one such
        # reading.
        "ci_profile_source": (os.path.basename(prof_path) if prof_path
                              else None),
        "ci_profile_scanned": prof.get("scanned"),
        "ci_profile_partial": prof.get("partial"),
        "ci_profile_from_cache": bool(prof.get("from_cache")),
        "scope_joined": PR_SCOPE,
        "rate": budget.summary(),
        "limitations": LIMITATIONS,
        "totals": totals(repos),
        "validation": validation(repos, prof),
        "repos": repos,
        # Not measured. None of these is a repository without fork pull
        # requests, and the reasons are kept apart because they call for
        # different things.
        "not_queried": missing,
        "not_queried_counts": reason_counts(missing),
    }
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
    log("FORK-BASED CONTRIBUTION: {}{}".format(
        doc["measured"], "  (PARTIAL RUN)" if doc["partial"] else ""))
    log("=" * 72)
    if doc["partial"]:
        log("  PARTIAL: {}".format(doc["partial_reason"]))
        log("  Every figure below is a lower bound over a subset of the "
            "corpus.")
    log("  targets asked            {}".format(doc["targets_asked"]))
    log("  repositories measured    {}".format(t["repos_measured"]))
    for reason, n in doc["not_queried_counts"].items():
        log("  not queried              {:5}  {}".format(n, reason))
    log("  cap per repository       {} pull requests, {}".format(
        doc["cap_per_repo"], doc["cap_order"]))
    log("  censored by that cap     {} repositories{}".format(
        t["repos_capped"],
        "  <- their counts are lower bounds" if t["repos_capped"] else ""))
    log("")
    log("  DOES THIS CORPUS RECEIVE FORK CONTRIBUTION AT ALL?")
    log("    pull requests, all states          {}".format(t["prs_total"]))
    log("    repositories with any pull request {} of {}".format(
        t["repos_with_any_pr"], t["repos_measured"]))
    log("    fork pull requests (isCrossRepository) {}".format(t["fork_prs"]))
    log("    repositories with one               {}".format(
        t["repos_with_fork_pr"]))
    log("    ...from a fork someone else owns    {} pull requests across {} "
        "repositories".format(t["fork_prs_external_owner"],
                              t["repos_with_external_fork_pr"]))
    if not t["fork_prs"]:
        log("")
        log("    *** NO FORK PULL REQUEST EXISTS ANYWHERE IN THE MEASURED")
        log("    *** CORPUS. There is nothing to validate the CI classifier")
        log("    *** against, and the contributor question is theoretical for")
        log("    *** this corpus until contribution exists: an argument")
        log("    *** about participation, not about runners. That absence is")
        log("    *** the finding.")
    log("")
    log("  CI OUTCOME ON FORK PULL REQUESTS (head commit rollup)")
    for b in BUCKETS:
        n = t["fork_pr_outcomes"].get(b, 0)
        note = {NO_CHECKS: "   nothing attached, NOT a failure",
                HEAD_UNAVAILABLE: "   evidence gap, not a result",
                FAILED: "   proves nothing on its own"}.get(b, "")
        log("    {:18} {:6}{}".format(b, n, note))
    if t["rollup_disagreements"]:
        log("    (the PR-level rollup disagreed with the head commit's on {} "
            "pull requests; the commit's is what is used)".format(
                t["rollup_disagreements"]))
    log("")
    log("  repositories with a PASSING fork pull request {}".format(
        t["repos_with_passing_fork_pr"]))
    log("  ...where the pass is proven secret-free      {}".format(
        t["repos_proven"]))
    log("")
    log("-" * 72)
    log("VALIDATION AGAINST {} (scanned {}, scope {})".format(
        doc["ci_profile_source"], doc["ci_profile_scanned"],
        doc["scope_joined"]))
    if doc.get("ci_profile_from_cache"):
        log("  That profile was RE-ANALYSED FROM A CACHE, so the classes below "
            "describe")
        log("  the corpus as it was on the fetch date, not as it is now.")
    log("-" * 72)
    rows = doc["validation"]
    if not rows:
        log("  No repository in the measured corpus has a passing fork pull")
        log("  request, so this measurement validates nothing about the")
        log("  classifier. That is a statement about contribution, not about "
            "CI.")
    else:
        log("  A privileged class beside a passing fork run is a repository")
        log("  whose privilege was droppable: either the class is wrong or")
        log("  the credential was reporting-only.")
        log("")
        for r in rows:
            mark = ("CONTRADICTS" if r["contradicts_classifier"]
                    else "consistent")
            log("  [{}] {}".format(mark, r["repo"]))
            log("      classifier: {}{}      proof: {}".format(
                r["ci_class_pull_request"],
                " / " + r["ci_credentials_axis"]
                if r["ci_credentials_axis"] else "", r["proof"]))
            for p in r["passing_fork_prs"]:
                own = ("external fork" if p["external_owner"]
                       else "own-org fork")
                log("      #{} ({}, head {}) {}".format(
                    p["number"], own, p["head_owner"], p["verdict"]))
                if p["reason"]:
                    log("          why not proof: {}".format(p["reason"]))
                if p["checks"]:
                    log("          checks: {}".format(
                        ", ".join(c for c in p["checks"] if c)[:160]))
                if p["events"]:
                    log("          triggering events: {}".format(
                        ", ".join(p["events"])))
            log("")
    log("-" * 72)
    log("WHAT THIS ESTABLISHES, AND WHAT IT DOES NOT")
    log("-" * 72)
    for line in LIMITATIONS:
        log("  - " + _wrap(line, 68, "    "))
    log("")
    rate = doc["rate"]
    log("  requests {}   points spent {} of {}   remaining {}   resets {}"
        .format(rate["requests"], rate["spent_this_run"], rate["limit"],
                rate["remaining"], rate["resets_at"]))
    log("  nodes requested {}".format(rate["node_count_this_run"]))
    log("  written to {}".format(doc.get("output", FORK_NAME)))


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

USAGE = ("usage: python3 -m ciprofile.fork_observation --profile=PATH "
         "[--upstream=PATH] [--limit=N] [--cap=N] [--out=PATH]")


def parse_args(argv):
    """(limit, cap, profile, upstream, out). Hand-rolled to keep every
    spelling of a missing value a refusal rather than a default."""
    limit, cap, prof, upstream, out = None, DEFAULT_CAP, None, None, None
    for arg in argv:
        m = re.fullmatch(r"--limit(?:=(\d+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--limit needs a number: --limit=50")
            limit = int(m.group(1))
            continue
        m = re.fullmatch(r"--cap(?:=(\d+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--cap needs a number: --cap=100")
            cap = int(m.group(1))
            if cap < 1:
                raise SystemExit("--cap must be at least 1")
            continue
        # Which profile defines the corpus and supplies the classes to validate
        # against. Named rather than assumed, because the answer is a
        # judgement: a sweep's profile is the live reading, while a cached
        # re-analysis covers the same corpus off the cache.
        m = re.fullmatch(r"--profile(?:=(.+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--profile needs a path")
            prof = m.group(1)
            if not os.path.exists(prof):
                raise SystemExit("--profile: no such file {}".format(prof))
            continue
        m = re.fullmatch(r"--upstream(?:=(.+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--upstream needs a path")
            upstream = m.group(1)
            if not os.path.exists(upstream):
                raise SystemExit(
                    "--upstream: no such file {}".format(upstream))
            continue
        m = re.fullmatch(r"--out(?:=(.+))?", arg)
        if m:
            if not m.group(1):
                raise SystemExit("--out needs a path")
            out = m.group(1)
            continue
        raise SystemExit("unknown argument {!r}. {}".format(arg, USAGE))
    return limit, cap, prof, upstream, out


def main(argv=None):
    limit, cap, prof_path, upstream, out = parse_args(
        list(argv if argv is not None else sys.argv[1:]))
    if prof_path is None:
        raise SystemExit(
            "--profile is required: it defines both the corpus and the classes "
            "to validate against. " + USAGE)
    tok = token()
    github, missing = targets(prof_path, upstream)
    asked = len(github)
    if limit is not None:
        for key, _o, _n in github[limit:]:
            missing[key] = REASON_LIMIT
        github = github[:limit]
        asked = len(github)
    prof, _ = read_profile(prof_path)
    print("fork_observation: {} GitHub upstreams from the corpus, cap {} pull "
          "requests each".format(len(github), cap))
    print("  joining against {}{}".format(
        prof_path,
        " (RE-ANALYSED FROM A CACHE, not a live reading)"
        if prof.get("from_cache") else ""))
    for reason, n in reason_counts(missing).items():
        print("  {} not queried: {}".format(n, reason))
    budget = Budget()
    repos, gone, partial_reason = sweep(github, tok, budget, cap)
    missing.update(gone)
    doc = write(repos, missing, budget, cap, prof, partial_reason,
                path=out or os.path.join(os.path.dirname(prof_path) or ".",
                                         FORK_NAME),
                targets_asked=asked, limit=limit, prof_path=prof_path)
    report(doc)
    return doc


if __name__ == "__main__":
    main()
