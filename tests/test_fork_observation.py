#!/usr/bin/env python3
"""Fork pull requests as observation, and the two traps that flatter it.

Every check here runs with the socket layer taken away and the one HTTP call
site stubbed, so a stub that quietly fell through would fail rather than spend
somebody's rate budget from a test run.

The response shape is the first thing asserted, because it is read off a
published schema rather than from a live call: a wrong guess about a nesting
level would read as "this corpus has no fork contribution", which is the answer
one half expects and would therefore not question.
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile

import harness
from harness import run

harness.offline()

from ciprofile import fork_observation as f                      # noqa: E402
from ciprofile import report                                     # noqa: E402

f.PACE_SECONDS = 0
RATE = {"limit": 5000, "cost": 20, "remaining": 4800,
        "resetAt": "2026-10-10T22:00:00Z", "used": 200, "nodeCount": 2000}
PROF = {"scanned": "2026-10-10", "partial": False, "unknown": {},
        "source": {"source": "github"},
        "repos": {"own/a": {"pull_request": {
            "primary": "acts-on-forge",
            "flags": ["acts-on-forge", "credentials-unclear"]}}}}


def pr(num, cross=True, rollup="SUCCESS", head="outsider"):
    inner = {"state": rollup} if rollup else None
    return {"number": num, "state": "MERGED",
            "createdAt": "2026-01-01T00:00:00Z", "isCrossRepository": cross,
            "headRepositoryOwner": {"login": head},
            "author": {"login": head}, "statusCheckRollup": inner,
            "commits": {"totalCount": 1, "nodes": [
                {"commit": {"oid": "oid%d" % num,
                            "statusCheckRollup": inner}}]}}


def the_graphql_shape_parses_and_a_null_rollup_is_no_checks():
    def fake(query, tok, timeout=120):
        if "pullRequests {" in query:                       # pass 1, screen
            return {"data": {
                "r0": {"nameWithOwner": "own/a", "isArchived": False,
                       "pullRequests": {"totalCount": 4}},
                "r1": {"nameWithOwner": "own/b", "isArchived": False,
                       "pullRequests": {"totalCount": 0}},
                "rateLimit": RATE}}
        if "contexts(first" in query:                       # pass 3, evidence
            runinfo = {"event": "pull_request", "workflow": {"name": "CI"}}
            chk = {"__typename": "CheckRun", "name": "build",
                   "conclusion": "SUCCESS", "status": "COMPLETED",
                   "checkSuite": {"app": {"slug": "github-actions"},
                                  "workflowRun": runinfo}}
            roll = {"state": "SUCCESS",
                    "contexts": {"totalCount": 1, "nodes": [chk]}}
            node = {"number": 1, "commits": {"nodes": [
                {"commit": {"oid": "oid1", "statusCheckRollup": roll}}]}}
            return {"data": {"p0": {"pullRequest": node}, "rateLimit": RATE}}
        return {"data": {"r0": {"nameWithOwner": "own/a", "pullRequests": {
            "totalCount": 4, "nodes": [pr(1, rollup="SUCCESS"),
                                       pr(2, rollup=None),
                                       pr(3, rollup="FAILURE"),
                                       pr(4, cross=False)]}}},
            "rateLimit": RATE}
    f.post = fake
    budget = f.Budget()
    with contextlib.redirect_stdout(io.StringIO()):
        repos, missing, reason = f.sweep([("own/a", "own", "a"),
                                          ("own/b", "own", "b")], "t", budget,
                                         cap=100)
    assert reason is None, reason
    a = repos["own/a"]
    assert a["prs_total"] == 4 and a["prs_examined"] == 4, a
    # The one that is not isCrossRepository is not a fork pull request.
    assert a["fork_prs"] == 3 and a["fork_prs_external_owner"] == 3, a
    # A null rollup landed in no-checks and nowhere near failed: "nothing ran"
    # and "the checks failed" are different findings about a repository.
    assert a["outcomes"] == {"passed": 1, "failed": 1, "pending": 0,
                             "no-checks": 1, "head-unavailable": 0}, a
    got = dict((d["number"], d["outcome"]) for d in a["fork_pr_detail"])
    assert got == {1: "passed", 2: "no-checks", 3: "failed"}, got
    assert a["fork_pr_detail"][0]["head_oid"] == "oid1", a["fork_pr_detail"][0]
    # A green Actions run triggered by pull_request is the one thing that
    # proves the pipeline needed no repository secret.
    assert a["proof"] == "secret-free-proven", a.get("proof")
    # A repository that answered "no pull requests at all" is a measured zero
    # and stays a repository. It is NOT in not_queried.
    assert repos["own/b"]["prs_total"] == 0 and repos["own/b"]["fork_prs"] == 0
    assert missing == {}, missing


def the_five_buckets_and_what_makes_a_pass_proof():
    """The buckets at unit level, because the distinction between them is the
    whole reason this measurement is worth making. Two of the five are absences
    and neither may ever read as a result."""
    def node(rollup, commit=True):
        nodes = ([{"commit": {"oid": "abc", "statusCheckRollup": rollup}}]
                 if commit else [])
        return {"commits": {"totalCount": len(nodes), "nodes": nodes}}
    assert f.outcome(node({"state": "SUCCESS"}))[0] == "passed"
    assert f.outcome(node({"state": "FAILURE"}))[0] == "failed"
    assert f.outcome(node({"state": "ERROR"}))[0] == "failed"
    assert f.outcome(node({"state": "PENDING"}))[0] == "pending"
    assert f.outcome(node({"state": "EXPECTED"}))[0] == "pending"
    # A null rollup means nothing was attached to the commit, which GitHub's
    # own approval gate for first-time contributors produces. Never a failure.
    assert f.outcome(node(None)) == ("no-checks", None, "abc")
    # A commit the API would not hand over is a gap in the evidence, not a
    # result: a deleted fork can leave the head unreachable.
    assert f.outcome(node({"state": "SUCCESS"}, commit=False)) == \
        ("head-unavailable", None, None)
    assert f.outcome({"commits": {"nodes": [None]}})[0] == "head-unavailable"
    assert f.outcome({})[0] == "head-unavailable"
    # An enum value added to StatusState after this was written is not a pass.
    assert f.outcome(node({"state": "NEWTHING"}))[0] != "passed"
    # What a green rollup is worth. Only an Actions run triggered by
    # pull_request proves anything, because that is the event GitHub withholds
    # secrets from.
    act = {"kind": "check-run", "name": "build", "conclusion": "SUCCESS",
           "app": "github-actions", "workflow": "CI", "event": "pull_request"}
    assert f.judge([act]) == ("secret-free-proven", None)
    v, why = f.judge([dict(act, event="pull_request_target")])
    assert v == "passed-unproven" and "pull_request_target" in why, why
    st = {"kind": "status", "name": "ci/example", "conclusion": "SUCCESS",
          "app": None, "workflow": None, "event": None, "creator": "exampleci"}
    v, why = f.judge([st])
    assert v == "passed-unproven" and "not an Actions run" in why, why
    assert "exampleci" in why, why
    v, why = f.judge([])
    assert v == "passed-unproven" and "no check detail" in why, why
    v, why = f.judge([dict(act, event="push")])
    assert v == "passed-unproven" and "push" in why, why
    # One qualifying run among many is enough; the softer ones cannot take it
    # away.
    assert f.judge([st, dict(act, event="pull_request_target"), act])[0] \
        == "secret-free-proven"
    # Both arms of the StatusCheckRollupContext union are read, and a context
    # list longer than the page is SAID to be truncated.
    roll = {"state": "SUCCESS", "contexts": {"totalCount": 9, "nodes": [
        {"__typename": "CheckRun", "name": "build", "conclusion": "SUCCESS",
         "status": "COMPLETED",
         "checkSuite": {"app": {"slug": "github-actions"},
                        "workflowRun": {"event": "pull_request",
                                        "workflow": {"name": "CI"}}}},
        {"__typename": "StatusContext", "context": "ci/other",
         "state": "SUCCESS", "creator": {"login": "otherci"}}]}}
    pr_node = {"commits": {"nodes": [{"commit": {"oid": "x",
                                                 "statusCheckRollup": roll}}]}}
    checks, truncated, state = f.read_contexts(pr_node)
    assert (state, truncated) == ("SUCCESS", True), (state, truncated)
    assert checks[0]["app"] == "github-actions", checks[0]
    assert checks[0]["event"] == "pull_request" and checks[0]["workflow"] == "CI"
    assert checks[1]["kind"] == "status" and checks[1]["creator"] == "otherci"
    # A check run with no suite attached must not invent an event for itself.
    bare = {"commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts":
            {"totalCount": 1, "nodes": [{"__typename": "CheckRun", "name": "b",
             "conclusion": "SUCCESS", "status": "COMPLETED",
             "checkSuite": None}]}}}}]}}
    checks, truncated, _ = f.read_contexts(bare)
    assert checks[0]["event"] is None and truncated is False, checks
    assert f.judge(checks)[0] == "passed-unproven"
    # isCrossRepository is the CI predicate; a different fork OWNER is the
    # contribution predicate. An unknown owner is not read as our own.
    base = {"number": 1, "state": "OPEN", "createdAt": "z",
            "commits": {"nodes": []}}
    assert f.fork_record(dict(base, headRepositoryOwner={"login": "Own"}),
                         "own")["external_owner"] is False
    assert f.fork_record(dict(base, headRepositoryOwner={"login": "x"}),
                         "own")["external_owner"] is True
    none = f.fork_record(dict(base, headRepositoryOwner=None), "own")
    assert none["external_owner"] is False and none["head_owner"] is None


def the_cap_is_recorded_and_a_target_pass_is_not_proof():
    """A repository with thousands of pull requests must not spend the whole
    budget, so the counts are censored, and a censored count that does not
    announce itself is the one that gets quoted as a measurement."""
    def fake(query, tok, timeout=120):
        if "pullRequests {" in query:
            return {"data": {"r0": {"nameWithOwner": "own/a",
                                    "isArchived": False,
                                    "pullRequests": {"totalCount": 300}},
                             "rateLimit": RATE}}
        if "contexts(first" in query:
            runinfo = {"event": "pull_request_target",
                       "workflow": {"name": "CI"}}
            chk = {"__typename": "CheckRun", "name": "build",
                   "conclusion": "SUCCESS", "status": "COMPLETED",
                   "checkSuite": {"app": {"slug": "github-actions"},
                                  "workflowRun": runinfo}}
            roll = {"state": "SUCCESS",
                    "contexts": {"totalCount": 1, "nodes": [chk]}}
            node = {"number": 1, "commits": {"nodes": [
                {"commit": {"oid": "o1", "statusCheckRollup": roll}}]}}
            return {"data": {"p0": {"pullRequest": node}, "rateLimit": RATE}}
        assert "first: 2," in query, query
        return {"data": {"r0": {"nameWithOwner": "own/a", "pullRequests": {
            "totalCount": 300, "nodes": [pr(1), pr(2)]}}}, "rateLimit": RATE}
    f.post = fake
    budget = f.Budget()
    with contextlib.redirect_stdout(io.StringIO()):
        repos, missing, reason = f.sweep([("own/a", "own", "a")], "t", budget,
                                         cap=2)
    a = repos["own/a"]
    assert a["capped"] is True, a
    assert a["prs_total"] == 300 and a["prs_examined"] == 2, a
    path = os.path.join(tempfile.mkdtemp(), report.FORK_NAME)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        doc = f.write(repos, missing, budget, 2, PROF, reason, path=path,
                      targets_asked=1)
        f.report(doc)
    got = json.load(open(path))
    assert got["cap_per_repo"] == 2
    assert got["repos"]["own/a"]["capped"] is True
    assert got["totals"]["repos_capped"] == 1, got["totals"]
    said = out.getvalue()
    assert "cap per repository       2 pull requests" in said, said
    assert "censored by that cap     1 repositories" in said, said
    assert "lower bounds" in said, said
    # A green pull_request_target run ran in the BASE repository's context,
    # with its secrets, so it proves nothing. The flattering reading is the one
    # this measurement exists to avoid.
    assert got["repos"]["own/a"]["proof"] == "passed-unproven"
    row = got["validation"][0]
    assert row["contradicts_classifier"] is True, row
    assert row["ci_class_pull_request"] == "acts-on-forge", row
    assert row["ci_credentials_axis"] == "credentials-unclear", row
    assert "pull_request_target" in row["passing_fork_prs"][0]["reason"], row
    # ...and every such case is NAMED in the report, not merely counted.
    assert "CONTRADICTS" in said and "own/a" in said, said
    assert "pull_request_target" in said, said


def a_low_rate_budget_stops_the_run_and_writes_partial_results():
    """Under-claiming on failure, in the one place the flattering mistake is
    invisible: a repository nobody asked about looks exactly like a repository
    with no fork contribution, and a corpus of this kind is expected to have
    little."""
    f.SCREEN_BATCH = 2
    low = {"limit": 5000, "cost": 20, "remaining": 10,
           "resetAt": "2026-10-10T22:00:00Z", "used": 4990, "nodeCount": 2000}
    f.post = lambda query, tok, timeout=120: {"data": {
        "r0": {"nameWithOwner": "own/a", "isArchived": False,
               "pullRequests": {"totalCount": 7}},
        "r1": {"nameWithOwner": "own/b", "isArchived": False,
               "pullRequests": {"totalCount": 0}},
        "rateLimit": low}}
    budget = f.Budget()
    with contextlib.redirect_stdout(io.StringIO()):
        repos, missing, reason = f.sweep(
            [("own/a", "own", "a"), ("own/b", "own", "b"),
             ("own/c", "own", "c"), ("own/d", "own", "d")], "t", budget,
            cap=100)
    # It stopped rather than carrying on into a refusal, and it said what
    # stopped it in the budget's own figures rather than in a guess.
    assert reason and "screen pass stopped" in reason, reason
    assert "10 of 5000 points left" in reason, reason
    assert budget.requests == 1, budget.requests
    # own/b answered "no pull requests at all", which settles the fork question
    # for it: a measured zero, kept as a repository.
    assert set(repos) == {"own/b"}, set(repos)
    assert repos["own/b"]["prs_total"] == 0 and repos["own/b"]["fork_prs"] == 0
    # own/a was screened and has seven pull requests, but was never sampled, so
    # nothing is known about its forks. It must not appear as a repository
    # without fork contribution, and neither may the two never asked about.
    assert missing == {"own/a": "rate-budget-exhausted",
                       "own/c": "rate-budget-exhausted",
                       "own/d": "rate-budget-exhausted"}, missing
    path = os.path.join(tempfile.mkdtemp(), report.FORK_NAME)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        doc = f.write(repos, missing, budget, 100,
                      {"scanned": "x", "repos": {}, "unknown": {}}, reason,
                      path=path, targets_asked=4)
        f.report(doc)
    got = json.load(open(path))
    assert got["partial"] is True
    assert "screen pass stopped" in got["partial_reason"]
    assert got["not_queried_counts"] == {"rate-budget-exhausted": 3}, got
    assert got["rate"]["remaining"] == 10 and got["rate"]["floor"] == \
        budget.floor
    said = out.getvalue()
    assert "PARTIAL RUN" in said and "lower bound" in said, said
    assert "rate-budget-exhausted" in said, said
    # Nothing was measured, so the absence is stated as an absence of
    # MEASUREMENT rather than as an absence of contribution.
    assert "NO FORK PULL REQUEST EXISTS" in said, said
    assert "validates nothing about the" in said, said
    f.SCREEN_BATCH = 80


def the_target_set_read_only_by_construction_and_the_arguments():
    """The upstream HOST cannot be read off a repository's name, so a corpus key
    with nothing saying where it came from is unasked, not quiet."""
    d = tempfile.mkdtemp()
    json.dump({"repos": {"own/a": {}, "grp/b": {}, "own/c": {}},
               "unknown": {"own/d": {}}},
              open(os.path.join(d, "prof.json"), "w"))
    open(os.path.join(d, "up.txt"), "w").write(
        "own/a https://github.com/own/a.git\n"
        "grp/b https://gitlab.example.org/grp/sub/b.git\n")
    gh, skipped = f.targets(os.path.join(d, "prof.json"),
                            os.path.join(d, "up.txt"))
    assert gh == [("own/a", "own", "a")], gh
    # A non-GitHub upstream is skipped by name rather than guessed at...
    assert skipped["grp/b"] == "non-github-upstream", skipped
    # ...and one nothing maps is host-unknown. Neither is a repository without
    # fork pull requests, and the reasons stay apart because one is a gap in
    # the corpus's metadata and the other is out of scope by design.
    assert skipped["own/c"] == "host-unknown", skipped
    assert skipped["own/d"] == "host-unknown", skipped
    # The GitHub coordinates come off the mapping, not off the corpus key, so a
    # repository stored under another name is still asked about correctly.
    open(os.path.join(d, "up2.txt"), "w").write(
        "org/local https://github.com/up/stream\n")
    json.dump({"repos": {"org/local": {}}, "unknown": {}},
              open(os.path.join(d, "prof2.json"), "w"))
    assert f.targets(os.path.join(d, "prof2.json"),
                     os.path.join(d, "up2.txt"))[0] \
        == [("org/local", "up", "stream")]
    # And a profile the github source produced needs no mapping at all: its
    # keys ARE the coordinates.
    json.dump({"repos": {"own/a": {}}, "unknown": {},
               "source": {"source": "github"}},
              open(os.path.join(d, "prof3.json"), "w"))
    assert f.targets(os.path.join(d, "prof3.json"))[0] \
        == [("own/a", "own", "a")]
    # Read-only by construction. GraphQL is POST, so the verb cannot carry the
    # argument the way it does for a REST adapter; the word that would make
    # this a write must simply never appear, in the source or in any document
    # it builds.
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ciprofile", "fork_observation.py")).read()
    assert re.findall(r"method\s*=\s*.([A-Z]+).", src) == ["POST"], \
        re.findall(r"method\s*=\s*.([A-Z]+).", src)
    assert "mutation" not in src, "the word mutation appears in the source"
    for fn, args in [(f.screen_query, ([("k", "o", "n")],)),
                     (f.sample_query, ([("k", "o", "n")], 10)),
                     (f.evidence_query, ([("k", "o", "n", 1)],))]:
        q = fn(*args)
        assert q.lstrip().startswith("query {"), q[:40]
        assert "mutation" not in q
        assert q.count("{") == q.count("}"), q
    # Names arrive from somebody else's dataset, so they are escaped rather
    # than trusted to stay inside GitHub's own character set.
    raw = 'a"b'
    q = f.screen_query([("x", raw, "c")])
    assert json.dumps(raw) in q, q
    assert '"' + raw + '"' not in q, q
    # Numbers are forced to int, so nothing from a dataset reaches the query as
    # a bare token.
    assert "first: 5," in f.sample_query([("k", "o", "n")], "5")
    try:
        f.evidence_query([("k", "o", "n", "x")])
    except ValueError:
        pass
    else:
        raise AssertionError("a non-numeric pull-request number was "
                             "interpolated")
    # No argument spelling silently means "no cap", and the profile is never
    # assumed.
    assert f.parse_args([]) == (None, f.DEFAULT_CAP, None, None, None)
    assert f.parse_args(["--limit=5", "--cap=7"])[:2] == (5, 7)
    pj = os.path.join(d, "prof.json")
    assert f.parse_args(["--profile=" + pj])[2] == pj
    for bad in [["--limit"], ["--cap"], ["--cap=0"], ["--nonsense"],
                ["--profile"], ["--profile=/no/such/profile.json"],
                ["--upstream"], ["--upstream=/no/such/file"]]:
        try:
            f.parse_args(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError("parse_args accepted %r" % (bad,))
    # The pacing floor cannot be configured away.
    assert f.PACE_FLOOR >= 0.5, f.PACE_FLOOR
    for asked in ["0", "0.1", "-5", "", "nonsense", None]:
        assert f.pace_seconds(asked) == f.PACE_FLOOR, asked
    assert f.pace_seconds("3") == 3.0


def it_can_never_write_over_the_classifiers_outputs():
    """A sweep costs hours. The refusal is on the BASENAME, so this check can
    prove it while aiming every write at a scratch directory: a check that
    aimed at a real profile would destroy that file the moment the guard it is
    testing got mutated away, which is a bug in the test. See EXPERIMENTS.md,
    "A destructive test"."""
    scratch = tempfile.mkdtemp()
    for name in sorted(report.ALL_OUTPUT_NAMES - {report.FORK_NAME}):
        try:
            f.write({}, {}, f.Budget(), 1, {}, None,
                    path=os.path.join(scratch, name))
        except SystemExit as e:
            assert "refusing" in str(e), e
        else:
            raise AssertionError("wrote to " + name)
    assert os.listdir(scratch) == [], os.listdir(scratch)
    # The names it guards are the ones the classifier actually writes, read out
    # of that module rather than restated here, so a new output file there is
    # covered by construction instead of by somebody remembering this list.
    for owned in (report.PROFILE_NAME, report.CACHE_NAME,
                  report.FROM_CACHE_NAME):
        assert owned in report.ALL_OUTPUT_NAMES, owned
    f.write({}, {}, f.Budget(), 1, {}, None,
            path=os.path.join(scratch, report.FORK_NAME))
    assert os.listdir(scratch) == [report.FORK_NAME]


sys.exit(run([
    ("the GraphQL shape parses, and a null rollup is no-checks",
     the_graphql_shape_parses_and_a_null_rollup_is_no_checks),
    ("the five outcome buckets, and what makes a pass proof",
     the_five_buckets_and_what_makes_a_pass_proof),
    ("the cap is recorded where it bites, and a target pass is not proof",
     the_cap_is_recorded_and_a_target_pass_is_not_proof),
    ("a low rate budget stops the run and writes partial results",
     a_low_rate_budget_stops_the_run_and_writes_partial_results),
    ("the target set, read-only by construction, and the arguments",
     the_target_set_read_only_by_construction_and_the_arguments),
    ("it can never write over the classifier's outputs",
     it_can_never_write_over_the_classifiers_outputs),
]))
