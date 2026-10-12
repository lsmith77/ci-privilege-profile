#!/usr/bin/env python3
"""Whether the declared pipeline ever ran, and the two zeros that are not zeros.

Every check here runs with the socket layer taken away and the one HTTP call
site stubbed, so a stub that quietly fell through would fail rather than spend
somebody's rate budget from a test run.

The checks are weighted towards the distinction the whole measurement rests on:
a repository the API could not answer for must never read as a repository whose
pipeline never ran. The flattering mistake and the alarming mistake are the
same mistake here, so there is no direction in which a defect would look wrong.
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

import harness
from harness import run

harness.offline()

from ciprofile import ci_activity as a                           # noqa: E402
from ciprofile import report                                     # noqa: E402

a.PACE_SECONDS = 0
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)
HEADERS = {"x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4900",
           "x-ratelimit-used": "100", "x-ratelimit-reset": "1791000000"}


def runs(total, *conclusions, **kw):
    """A runs payload. `conclusions` are newest-first (conclusion, date)."""
    when = kw.get("when", "2026-10-11T00:00:00Z")
    return {"total_count": total,
            "workflow_runs": [
                {"conclusion": c, "status": "completed", "event": "push",
                 "created_at": d or when, "name": "CI", "workflow_id": 1}
                for c, d in conclusions]}


def stub(table):
    """Serve a {path-fragment: payload} table, and fail on anything else.

    A fragment rather than a whole path so a check states the thing it is about
    (the event restriction, the success probe) instead of restating the whole
    query string.
    """
    def fake(path, tok, timeout=60):
        for fragment, payload in table:
            if fragment in path:
                if isinstance(payload, Exception):
                    raise payload
                return payload, HEADERS
        raise AssertionError("no stub for " + path)
    return fake


def zero_total_is_never_ran_and_is_not_an_error():
    """The finding this measurement exists for: a declared pipeline that has
    done nothing. It is a measured zero and a kept repository, not a failure,
    and it must not cost a second request either."""
    asked = []

    def fake(path, tok, timeout=60):
        asked.append(path)
        return {"total_count": 0, "workflow_runs": []}, HEADERS
    a.get = fake
    budget = a.RestBudget()
    found, reason = a.measure("own", "a", "t", budget, now=NOW)
    assert reason is None, reason
    assert found[a.ALL_EVENTS]["runs_total"] == 0
    assert found[a.ALL_EVENTS]["ever_ran"] is False
    assert found[a.ALL_EVENTS]["status"] == "never-ran", found
    # No run of any kind means no successful run and no pull-request run.
    # Both are certainties rather than inferences, so neither is paid for.
    assert found[a.ALL_EVENTS]["successes_total"] == 0
    assert found[a.PULL_REQUEST]["status"] == "never-ran"
    assert found[a.PULL_REQUEST]["source"] == "implied-by-zero-total"
    assert len(asked) == 1, asked
    assert budget.requests == 1, budget.requests
    # And the budget came off the headers rather than out of a guess.
    assert budget.limit == 5000 and budget.remaining == 4900
    assert budget.summary()["requests_this_run"] == 1
    assert budget.summary()["unit"] == "requests per hour"


def an_unanswerable_repository_is_unknown_and_never_never_ran():
    """The one misreading that would look like a finding. Each failure mode
    gets its own reason because they call for different things, and not one of
    them may produce a status."""
    import urllib.error

    def http(code, headers=None):
        return urllib.error.HTTPError("u", code, "m", headers or {}, None)

    cases = [(404, "upstream-absent"), (403, "actions-unavailable")]
    for code, want in cases:
        a.get = stub([("actions/runs", http(code))])
        budget = a.RestBudget()
        found, reason = a.measure("own", "a", "t", budget, now=NOW)
        assert found is None and reason == want, (code, found, reason)
    # A batch nobody answered after every attempt is `query-unanswered`, which
    # is also not a zero.
    a.get = stub([("actions/runs", TimeoutError("slow"))])
    budget = a.RestBudget()
    with contextlib.redirect_stderr(io.StringIO()):
        a.ATTEMPTS, keep = 1, a.ATTEMPTS
        found, reason = a.measure("own", "a", "t", budget, now=NOW)
        a.ATTEMPTS = keep
    assert found is None and reason == "query-unanswered", (found, reason)
    # A payload with no integer total is not read as zero. A missing key and a
    # null are both answers this cannot use, and `total_count: true` is the one
    # a bool-is-an-int language would otherwise accept as 1.
    for body in [{}, {"total_count": None}, {"total_count": "4"},
                 {"total_count": True}, []]:
        assert a.read_runs(body)[0] is None, body
    # None of those reasons may ever be a status, and `unknown` is the only
    # status that is not derived from a measurement.
    for reason in ("upstream-absent", "actions-unavailable",
                   "query-unanswered", "non-actions-pipeline",
                   "rate-budget-exhausted"):
        assert reason not in a.STATUSES, reason
    # The written figures put every unmeasured repository in `unknown` rather
    # than letting it vanish from the denominator.
    totals = a.totals({}, {"own/x": "upstream-absent",
                           "own/y": "non-actions-pipeline"})
    for name in (a.ALL_EVENTS, a.PULL_REQUEST):
        assert totals[name]["unknown"] == 2, totals[name]
        assert totals[name]["never_ran"] == 0, totals[name]


def the_statuses_and_the_recency_window_that_defines_them():
    """`passing` is a claim about a window, so the window decides it. A green
    run from last year is not a working check today, and a status that ignored
    the date would say it was."""
    def rec(total, *conclusions, **kw):
        _, got = a.read_runs(runs(total, *conclusions, **kw))
        return {"ever_ran": total > 0,
                "last_run_at": got[0]["created_at"] if got else None,
                "recent_runs": got}
    def status(total, *conclusions, **kw):
        days = kw.pop("days", a.RECENT_DAYS)
        return a.derive_status(rec(total, *conclusions, **kw), days, NOW)
    assert status(0) == "never-ran"
    assert status(3, ("success", None)) == "passing"
    assert status(3, ("failure", None)) == "failing"
    assert status(3, ("timed_out", None)) == "failing"
    assert status(3, ("startup_failure", None)) == "failing"
    # An approval gate is neither a pass nor a failure of the pipeline, and
    # merging it into either would be inventing a verdict.
    assert status(3, ("action_required", None)) == "awaiting-approval"
    assert status(3, ("cancelled", None)) == "inconclusive"
    assert status(3, (None, None)) == "inconclusive"
    # A conclusion added to the API after this was written is not a pass.
    assert status(3, ("newthing", None)) == "inconclusive"
    # The newest CONCLUDED run decides, so a run still in flight does not hide
    # the verdict underneath it.
    assert status(3, (None, "2026-10-11T00:00:00Z"),
                  ("failure", "2026-10-10T00:00:00Z")) == "failing"
    # 418 runs ending ten months ago is not "currently passing". This is the
    # case the corpus actually produced and the one a window-free reading would
    # get wrong.
    assert status(418, ("success", "2025-12-10T00:00:00Z")) == "ran-not-recently"
    assert status(418, ("success", "2025-12-10T00:00:00Z"),
                  days=400) == "passing"
    # The boundary is the window and not a day either side of it.
    assert status(2, ("success", "2026-09-13T00:00:00Z")) == "passing"
    assert status(2, ("success", "2026-09-11T00:00:00Z")) == "ran-not-recently"
    # Runs counted and none on the page is an answer this cannot use. Not a
    # zero, and not a verdict.
    assert a.derive_status({"ever_ran": True, "last_run_at": None,
                            "recent_runs": []}, 30, NOW) == "inconclusive"
    # A timestamp in a shape the API does not emit is not guessed at.
    assert a.parse_time(None) is None and a.parse_time("yesterday") is None
    assert a.parse_time("2026-10-11T00:00:00Z").year == 2026
    # Every status the output can carry has a published meaning, so a reader
    # meeting one in the JSON is not sent to the source.
    for s in a.STATUSES:
        assert s in a.STATUS_MEANS, s


def the_pull_request_restriction_is_applied_and_counted_apart():
    """The scope the rest of the tool quotes. A repository busy with push runs
    and silent on pull requests has a dead pull-request pipeline, and one
    figure covering both would hide exactly that."""
    seen = []

    def fake(path, tok, timeout=60):
        seen.append(path)
        if "event=pull_request" in path:
            if "status=success" in path:
                return runs(0), HEADERS
            return runs(0), HEADERS
        if "status=success" in path:
            return runs(40, ("success", "2026-10-11T00:00:00Z")), HEADERS
        return runs(40, ("success", "2026-10-11T00:00:00Z")), HEADERS
    a.get = fake
    budget = a.RestBudget()
    found, reason = a.measure("own", "a", "t", budget, now=NOW)
    assert reason is None, reason
    # The restriction reached the wire, spelled as the API documents it.
    assert any("event=pull_request" in p for p in seen), seen
    # Three requests and not four: the pull-request scope answered zero, and
    # no run at all is no successful run, so the probe is not paid for.
    assert len(seen) == 3, seen
    assert sum(1 for p in seen if "status=success" in p) == 1, seen
    assert not any("event=pull_request" in p and "status=success" in p
                   for p in seen), seen
    # Live overall, dead on the event that matters, and the two are reported
    # separately rather than reconciled.
    assert found[a.ALL_EVENTS]["status"] == "passing"
    assert found[a.ALL_EVENTS]["runs_total"] == 40
    assert found[a.PULL_REQUEST]["status"] == "never-ran"
    assert found[a.PULL_REQUEST]["runs_total"] == 0
    # The success probe is what makes last_success_at exact rather than "no
    # success inside the newest page", and a scope with no success at all gets
    # a null rather than a borrowed date.
    assert found[a.ALL_EVENTS]["last_success_at"] == "2026-10-11T00:00:00Z"
    assert found[a.PULL_REQUEST]["last_success_at"] is None
    # The path builder percent-encodes names from somebody else's dataset and
    # forces every query value into a known shape.
    p = a.runs_path("o w", "n/m", event="pull_request", per_page="20",
                    status="success")
    assert "o%20w" in p and "n%2Fm" in p, p
    assert "per_page=20" in p and "event=pull_request" in p, p
    assert "status=success" in p, p
    # The totals carry the two scopes apart, with the denominator on each.
    repos = {"own/a": dict({"repo": "own/a", "upstream": "own/a",
                            "upstream_from": "fork-observation"}, **found)}
    t = a.totals(repos, {})
    assert t[a.ALL_EVENTS]["ever_ran"] == 1
    assert t[a.ALL_EVENTS]["ran_recently"] == 1
    assert t[a.PULL_REQUEST]["never_ran"] == 1
    assert t[a.PULL_REQUEST]["ran_recently"] == 0
    assert t[a.PULL_REQUEST]["runs_recorded"] == 0


def a_renamed_upstream_is_joined_on_the_name_github_answered():
    """The known trap. The corpus keys repositories by the mirror's name and
    the upstream has to be asked about under its current one, so a join on
    either name alone loses repositories in one direction."""
    d = tempfile.mkdtemp()
    prof = {"repos": {
        # Renamed and transferred upstream: the key is the mirror's name.
        "sitn/django-extended-ol": {"pull_request": {
            "primary": "autark", "flags": [],
            "files": [".github/workflows/ci.yml"]}},
        # Not GitHub Actions at all. Its zero would be the wrong API's zero.
        "grp/gitlab-only": {"pull_request": {
            "primary": "autark", "flags": [], "files": [".gitlab-ci.yml"]}},
        # Actions beside a second grammar: asked about, and said to be partial.
        "own/mixed": {"pull_request": {
            "primary": "autark", "flags": [],
            "files": [".github/workflows/ci.yml", ".gitlab-ci.yml"]}},
        # No pull-request-triggered pipeline, so not a candidate at all.
        "own/nothing": {"pull_request": {"primary": "no-pipeline",
                                         "flags": [], "files": []}},
        "own/notrigger": {"pull_request": {
            "primary": "no-pull-request-trigger", "flags": [], "files": []}},
        # The fork observation could not establish a host for this one.
        "own/hostless": {"pull_request": {
            "primary": "autark", "flags": [],
            "files": [".github/workflows/ci.yml"]}},
        # It reached for this one and got no answer, which leaves the host
        # established and only the response missing.
        "own/silent": {"pull_request": {
            "primary": "autark", "flags": [],
            "files": [".github/workflows/ci.yml"]}},
    }, "unknown": {}}
    json.dump(prof, open(os.path.join(d, "prof.json"), "w"))
    fork = {"repos": {
        "sitn/django-extended-ol": {
            "name_with_owner": "sitn/sitn-django-plugins"},
        "own/mixed": {"name_with_owner": "own/mixed"},
        "grp/gitlab-only": {"name_with_owner": "grp/gitlab-only"},
    }, "not_queried": {"own/hostless": "host-unknown",
                       "own/silent": "query-unanswered"}}
    json.dump(fork, open(os.path.join(d, "fork.json"), "w"))
    wanted, skipped = a.targets(os.path.join(d, "prof.json"),
                                os.path.join(d, "fork.json"))
    by_key = dict((t["repo"], t) for t in wanted)
    # The upstream is asked about under the name GitHub answered with, and both
    # names travel, because a report carrying only one could not be checked
    # against either forge.
    row = by_key["sitn/django-extended-ol"]
    assert row["upstream"] == "sitn/sitn-django-plugins", row
    assert row["upstream_owner"] == "sitn" and row["upstream_name"] == \
        "sitn-django-plugins", row
    assert row["renamed_since_mirror"] is True, row
    assert row["upstream_from"] == "fork-observation", row
    assert by_key["own/mixed"]["renamed_since_mirror"] is False
    assert by_key["own/mixed"]["other_grammar_files"] == 1
    assert by_key["own/mixed"]["workflow_files"] == 1
    # A GitLab pipeline has no Actions runs by construction, so it is not asked
    # about and above all not recorded as a pipeline that never ran.
    assert skipped["grp/gitlab-only"] == "non-actions-pipeline", skipped
    assert "grp/gitlab-only" not in by_key
    # A key the fork observation could not place is carried over as its own
    # reason and never guessed at from the key.
    assert skipped["own/hostless"] == "host-unknown", skipped
    # A key it reached for and did not get an answer about keeps the host, so
    # the key may stand in. That is the only fallback, and it is named.
    assert by_key["own/silent"]["upstream_from"] == "corpus-key", by_key
    assert by_key["own/silent"]["upstream"] == "own/silent"
    # Repositories with no pull-request-triggered pipeline are not candidates
    # and are not skips either: they are outside the selected corpus.
    assert "own/nothing" not in by_key and "own/nothing" not in skipped
    assert "own/notrigger" not in by_key and "own/notrigger" not in skipped
    # A mapping file states the HOST, which no name can, and a non-GitHub
    # upstream is skipped by name rather than asked of the wrong API.
    open(os.path.join(d, "up.txt"), "w").write(
        "own/hostless https://gitlab.example.org/grp/sub/hostless.git\n")
    wanted2, skipped2 = a.targets(os.path.join(d, "prof.json"),
                                  os.path.join(d, "fork.json"),
                                  os.path.join(d, "up.txt"))
    assert skipped2["own/hostless"] == "non-github-upstream", skipped2
    # Where both files cover a key the ANSWER wins over the assertion, because
    # the mapping file cannot know about a rename that happened after it was
    # written.
    open(os.path.join(d, "up2.txt"), "w").write(
        "sitn/django-extended-ol github.com-less/stale\n"
        "sitn/django-extended-ol https://github.com/sitn/django-extended-ol\n")
    wanted3, _ = a.targets(os.path.join(d, "prof.json"),
                           os.path.join(d, "fork.json"),
                           os.path.join(d, "up2.txt"))
    row3 = dict((t["repo"], t) for t in wanted3)["sitn/django-extended-ol"]
    assert row3["upstream"] == "sitn/sitn-django-plugins", row3
    assert row3["upstream_from"] == "fork-observation", row3
    # The mapping reader is the fork observation's, imported rather than
    # re-derived: one spelling of a mapping file for both measurements.
    from ciprofile import fork_observation
    assert a.read_upstreams is fork_observation.read_upstreams
    # A fork file whose name_with_owner is missing or malformed yields no name
    # rather than half of one.
    json.dump({"repos": {"k": {"name_with_owner": None},
                         "j": {"name_with_owner": "no-slash"},
                         "i": {"name_with_owner": "a/b/c"}},
               "not_queried": {}}, open(os.path.join(d, "bad.json"), "w"))
    assert a.fork_upstreams(os.path.join(d, "bad.json"))[0] == {}


def a_low_budget_stops_cleanly_and_writes_partial_results():
    """Under-claiming on failure, in the place where the mistake is invisible:
    a repository nobody asked about looks exactly like one whose pipeline never
    ran, which is the finding being reported."""
    low = dict(HEADERS, **{"x-ratelimit-remaining": "3"})
    # The budget runs out on the last request of the first repository, so the
    # repository in flight is finished and the next one is never begun. A
    # half-measured repository must never be recorded, which is what the
    # check-before-the-call ordering buys.
    spent = []

    def fake(path, tok, timeout=60):
        spent.append(path)
        return (runs(2, ("success", "2026-10-11T00:00:00Z")),
                low if len(spent) >= 4 else HEADERS)
    a.get = fake
    budget = a.RestBudget(floor=60)
    wanted = [{"repo": "own/%s" % n, "upstream": "own/%s" % n,
               "upstream_owner": "own", "upstream_name": n,
               "upstream_from": "fork-observation",
               "renamed_since_mirror": False, "workflow_files": 1,
               "other_grammar_files": 0} for n in "abcd"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        repos, missing, partial = a.sweep(wanted, "t", budget, now=NOW)
    # It stopped rather than carrying on into a refusal, and it said what
    # stopped it in the budget's own figures rather than in a guess.
    assert partial and "3 of 5000 requests left" in partial, partial
    assert "stopped after 1 of 4" in partial, partial
    assert len(spent) == 4, spent
    assert set(repos) == {"own/a"}, set(repos)
    assert missing == dict((k, "rate-budget-exhausted")
                           for k in ["own/b", "own/c", "own/d"]), missing
    # The floor is the fork observation's, inherited rather than restated, so
    # the one decision about when to stop is shared.
    from ciprofile import fork_observation
    assert issubclass(a.RestBudget, fork_observation.Budget)
    path = os.path.join(tempfile.mkdtemp(), report.ACTIVITY_NAME)
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        doc = a.write(repos, missing, budget, {"scanned": "x"}, partial,
                      path=path, targets_asked=4, measured_at=NOW)
        a.report(doc)
    got = json.load(open(path))
    assert got["partial"] is True
    assert "stopped after" in got["partial_reason"]
    assert got["not_queried_counts"] == {"rate-budget-exhausted": 3}, got
    assert got["rate"]["remaining"] == 3 and got["rate"]["floor"] == 60
    # The partial results survived, which is the point of stopping above a
    # floor rather than at the bottom of the budget.
    assert got["repos"]["own/a"][a.ALL_EVENTS]["status"] == "passing"
    # The three unreached repositories are unknown in both scopes and never
    # never-ran.
    for name in (a.ALL_EVENTS, a.PULL_REQUEST):
        assert got["totals"][name]["unknown"] == 3, got["totals"][name]
        assert got["totals"][name]["never_ran"] == 0
    text = said.getvalue()
    assert "PARTIAL RUN" in text and "subset" in text, text
    assert "rate-budget-exhausted" in text, text
    # The window is in the output and in the print, because every figure using
    # the word recently moves with it.
    assert got["recent_window_days"] == a.RECENT_DAYS
    assert "30 days of measured_at" in got["recent_window_means"]
    assert "30 days" in text, text
    # And the report says whose activity this is, every time.
    assert "UPSTREAM" in text and "holding the mirror" in text, text


def the_control_separates_a_fidelity_gap_from_a_dead_pipeline():
    """The second use, and the reason the first one is worth the requests. An
    environment failure on a pipeline that passes upstream is a gap in the
    local runner; the same failure on a pipeline that has never run is a dead
    pipeline, and the two call for opposite conclusions."""
    assert a.control_reading("environment-failure", "passing") == \
        "fidelity-gap"
    assert a.control_reading("environment-failure", "never-ran") == \
        "dead-pipeline"
    assert a.control_reading("timed-out", "never-ran") == "dead-pipeline"
    assert a.control_reading("not-attempted", "never-ran") == "dead-pipeline"
    # Failing upstream too is neither: the pipeline is broken wherever it runs.
    assert a.control_reading("environment-failure", "failing") == \
        "failing-upstream-too"
    assert a.control_reading("environment-failure", "ran-not-recently") == \
        "no-current-upstream-run"
    # Unknown buys no reading in either direction, which is the same asymmetry
    # the rest of this tool holds to.
    assert a.control_reading("environment-failure", "unknown") == \
        "not-decidable"
    assert a.control_reading("environment-failure", "awaiting-approval") == \
        "not-decidable"
    # An outcome the local run answered on its own needs no control, and the
    # upstream status must not be allowed to overturn it.
    for outcome in ("ran-unprivileged", "ran-with-failures",
                    "secret-required"):
        assert a.control_reading(outcome, "never-ran") == \
            "local-run-answered", outcome
    # Every reading the output can carry has a published meaning.
    for row in a.CONTROL_MEANS:
        assert row in (a.CONTROL_FIDELITY, a.CONTROL_DEAD, a.CONTROL_BROKEN,
                       a.CONTROL_STALE, a.CONTROL_UNDECIDABLE,
                       a.CONTROL_ANSWERED), row
    # The join is on the differential output's own repository key, and a
    # repository the sweep could not measure comes through as a row carrying
    # the reason rather than being dropped from the table.
    d = tempfile.mkdtemp()
    path = os.path.join(d, "differential_execution.json")
    json.dump({"run": "2026-10-12", "repositories": [
        {"repo": "own/a", "outcome": "environment-failure"},
        {"repo": "own/gone", "outcome": "environment-failure"},
        {"outcome": "environment-failure"}]}, open(path, "w"))
    read = a.read_differential([path])
    assert read[0][2] == {"own/a": "environment-failure",
                          "own/gone": "environment-failure"}, read
    repos = {"own/a": {"upstream": "own/a",
                       a.PULL_REQUEST: {"status": "passing", "runs_total": 9,
                                        "last_success_at": "2026-10-11"},
                       a.ALL_EVENTS: {"status": "passing",
                                      "runs_total": 30}}}
    rows = a.control(repos, {"own/gone": "upstream-absent"}, read)
    assert [r["reading"] for r in rows] == ["fidelity-gap", "not-decidable"]
    assert rows[1]["unknown_reason"] == "upstream-absent", rows[1]
    assert rows[0]["upstream_runs_pull_request"] == 9
    # The reading rests on the PULL-REQUEST status, because that is the event
    # differential execution runs, and a repository busy on push with nothing
    # on pull requests is a dead pull-request pipeline.
    repos["own/a"][a.PULL_REQUEST] = {"status": "never-ran", "runs_total": 0,
                                      "last_success_at": None}
    rows = a.control(repos, {}, read)
    assert rows[0]["reading"] == "dead-pipeline", rows[0]
    assert rows[0]["upstream_status_all_events"] == "passing", rows[0]


def it_is_read_only_and_can_never_write_over_another_output():
    """A sweep costs hours. The refusal is on the BASENAME, so this check can
    prove it while aiming every write at a scratch directory: a check aimed at
    a real profile would destroy that file the moment the guard it is testing
    got mutated away, which is a bug in the test. See EXPERIMENTS.md, "A
    destructive test"."""
    scratch = tempfile.mkdtemp()
    for name in sorted(report.ALL_OUTPUT_NAMES - {report.ACTIVITY_NAME}):
        try:
            a.write({}, {}, a.RestBudget(), {}, None,
                    path=os.path.join(scratch, name), measured_at=NOW)
        except SystemExit as e:
            assert "refusing" in str(e), e
        else:
            raise AssertionError("wrote to " + name)
    assert os.listdir(scratch) == [], os.listdir(scratch)
    # The names it guards are read out of the report module rather than
    # restated here, so a new output file there is covered by construction.
    assert report.ACTIVITY_NAME in report.ALL_OUTPUT_NAMES
    a.write({}, {}, a.RestBudget(), {}, None,
            path=os.path.join(scratch, report.ACTIVITY_NAME), measured_at=NOW)
    assert os.listdir(scratch) == [report.ACTIVITY_NAME]
    # Read-only by construction: no verb is named anywhere in the module, so
    # there is no argument to get wrong, and there is one call site to stub.
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ciprofile", "ci_activity.py")).read()
    assert re.findall(r"method\s*=\s*.([A-Z]+).", src) == [], src[:0]
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in src, verb
    assert src.count("urlopen") == 1, src.count("urlopen")
    assert "data=" not in src, "a request body would make this a write"
    # No argument spelling silently means a default, and neither the corpus nor
    # the upstream mapping is ever assumed.
    assert a.parse_args([]) == (None, None, None, [], a.RECENT_DAYS, None,
                                None)
    for bad in [["--profile"], ["--profile=/no/such/file"], ["--fork"],
                ["--fork=/no/such/file"], ["--upstream"],
                ["--differential"], ["--differential=/no/such/file"],
                ["--recent-days"], ["--recent-days=0"], ["--limit"],
                ["--out"], ["--nonsense"]]:
        try:
            a.parse_args(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError("parse_args accepted %r" % (bad,))
    # A corpus of mirrors cannot be asked about under the mirrors' own names,
    # so main refuses without a mapping rather than measuring the wrong thing.
    here = os.path.abspath(__file__)
    for argv in ([], ["--profile=" + here]):
        try:
            a.main(argv)
        except SystemExit as e:
            assert "required" in str(e), e
        else:
            raise AssertionError("main accepted %r" % (argv,))
    # The pacing floor cannot be configured away.
    assert a.PACE_SECONDS == 0  # taken away for the checks, deliberately
    from ciprofile import fork_observation
    assert a.pace_seconds is fork_observation.pace_seconds
    for asked in ["0", "0.1", "-5", "", "nonsense", None]:
        assert a.pace_seconds(asked) == fork_observation.PACE_FLOOR, asked


sys.exit(run([
    ("zero total runs is never-ran, and is not an error",
     zero_total_is_never_ran_and_is_not_an_error),
    ("an unanswerable repository is unknown and never never-ran",
     an_unanswerable_repository_is_unknown_and_never_never_ran),
    ("the statuses, and the recency window that defines them",
     the_statuses_and_the_recency_window_that_defines_them),
    ("the pull-request restriction is applied and counted apart",
     the_pull_request_restriction_is_applied_and_counted_apart),
    ("a renamed upstream is joined on the name GitHub answered",
     a_renamed_upstream_is_joined_on_the_name_github_answered),
    ("a low budget stops cleanly and writes partial results",
     a_low_budget_stops_cleanly_and_writes_partial_results),
    ("the control separates a fidelity gap from a dead pipeline",
     the_control_separates_a_fidelity_gap_from_a_dead_pipeline),
    ("it is read-only and can never write over another output",
     it_is_read_only_and_can_never_write_over_another_output),
]))
