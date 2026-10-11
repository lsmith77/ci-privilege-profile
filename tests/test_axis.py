#!/usr/bin/env python3
"""The reporting-versus-test-time axis, and the asymmetry that keeps it honest.

This axis is the most-argued part of the tool and the one whose headline
finding is negative: the band it produces is too wide to quote. EXPERIMENTS.md
carries that finding. These checks pin the mechanism anyway, because the
mechanism is what makes the band *honest*; remove the asymmetry and the
figure becomes flattering rather than merely wide.
"""
import sys

import harness
from harness import run

harness.offline()

from ciprofile import rules                                      # noqa: E402
from ciprofile.classify import (ACTS_ON_FORGE, ASIDE,            # noqa: E402
                                CREDENTIALS_REPORTING_ONLY,
                                CREDENTIALS_TEST_TIME,
                                CREDENTIALS_UNCLEAR, GROUPS, PRECEDENCE,
                                PR_SCOPE, READ_CREDENTIAL, REPO_SCOPE,
                                classify, contributor_runnable)
from ciprofile.fixtures import fixture_cases                     # noqa: E402

CASES = fixture_cases()
JOB = ("on:\n  pull_request:\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
       "    steps:\n")


def w(body, scope=PR_SCOPE):
    return classify({".github/workflows/w.yml": body})[scope]


def a_secret_that_only_feeds_a_reporting_step_is_counted():
    """The axis's own case, and the one the derived figure exists for:
    unprivileged tests, one secret, and it reaches a coverage uploader. The
    repository needs a credential as written and a contributor could still run
    its tests, which is the finding `self-contained` cannot report."""
    prof = classify(CASES["reporting-coverage-upload"])
    p = prof[PR_SCOPE]
    assert p["primary"] == READ_CREDENTIAL, p
    assert CREDENTIALS_REPORTING_ONLY in p["flags"], p
    assert "reporting-coverage" in p["signals"], p
    # Counted, and counted as the second term: the figure is self-contained
    # plus this.
    assert contributor_runnable({"o/r": prof})[:3] == (1, 0, 1), prof
    # The forge-side twin, which is why the axis is not a subdivision of
    # read-credential: acts-on-forge, and as runnable as a self-contained
    # repository, because all the forge privilege buys is a comment.
    forge = classify(CASES["reporting-pr-comment"])
    fp = forge[PR_SCOPE]
    assert fp["primary"] == ACTS_ON_FORGE, fp
    assert CREDENTIALS_REPORTING_ONLY in fp["flags"], fp
    assert contributor_runnable({"o/r": forge})[:3] == (1, 0, 1), forge


def a_dependency_resolution_credential_is_test_time():
    """The inverse, where the credential is what resolves the dependencies:
    nothing runs without it, so no amount of reporting shape can make the scope
    droppable. It has to be decisive, because it is the signal that keeps the
    hopeful reading honest."""
    for case, signal in [("credentials-test-time-maven", "dep-credential-jvm"),
                         ("read-credential", "dep-credential-npm")]:
        prof = classify(CASES[case])
        p = prof[PR_SCOPE]
        assert CREDENTIALS_TEST_TIME in p["flags"], (case, p)
        assert signal in p["signals"], (case, p)
        assert contributor_runnable({"o/r": prof})[0] == 0, (case, prof)

    def npm(step):
        return w("on:\n  pull_request:\njobs:\n  t:\n"
                 "    runs-on: ubuntu-latest\n    env:\n"
                 "      NODE_AUTH_TOKEN: ${{ secrets.REGISTRY }}\n"
                 "    steps:\n      - run: " + step + "\n")
    pull = npm("npm ci")
    assert "dep-credential-npm" in pull["signals"], pull
    assert CREDENTIALS_TEST_TIME in pull["flags"], pull
    # And a publish is not dependency resolution. The same credential beside an
    # `npm publish` explains itself, so the rule stays silent rather than
    # reading a release step as something the tests need. Every TEST_TIME rule
    # carries that guard, and without it a release workflow would read as
    # test-time in bulk.
    push = npm("npm ci && npm publish")
    assert "dep-credential-npm" not in push["signals"], push
    assert CREDENTIALS_TEST_TIME not in push["flags"], push
    assert CREDENTIALS_UNCLEAR in push["flags"], push


def one_unrecognised_privileged_step_denies_reporting_only():
    """THE ASYMMETRY, which is the rule the whole axis rests on. Reporting-only
    is a positive claim about every privileged step in a scope, so one step
    nothing recognised has to be enough to deny it; otherwise the flattering
    answer wins by default for every tool the tables have never heard of, and
    the figure becomes a measure of the tables rather than of the corpus."""
    prof = classify(CASES["reporting-plus-unknown"])
    mix = prof[PR_SCOPE]
    # The recognised step is still recognised. What changes is the verdict.
    assert "reporting-coverage" in mix["signals"], mix
    assert rules.UNRECOGNISED_PRIVILEGED_STEP in mix["signals"], mix
    assert CREDENTIALS_UNCLEAR in mix["flags"], mix
    assert CREDENTIALS_REPORTING_ONLY not in mix["flags"], mix
    assert contributor_runnable({"o/r": prof})[0] == 0, prof
    # Stated over every combination rather than over one fixture.
    for extra in [set(), {"reporting-coverage"}, set(rules.REPORTING_SIGNALS),
                  set(rules.UNCLEAR_SIGNALS)]:
        for blocker in sorted(rules.UNCLEAR_SIGNALS):
            got = rules.credentials_purpose(extra | {blocker})
            assert got == CREDENTIALS_UNCLEAR, (extra, blocker, got)
        for timed in sorted(rules.TEST_TIME_SIGNALS):
            got = rules.credentials_purpose(extra | {timed})
            assert got == CREDENTIALS_TEST_TIME, (extra, timed, got)
    assert rules.credentials_purpose({"reporting-coverage"}) \
        == CREDENTIALS_REPORTING_ONLY
    assert rules.credentials_purpose(set()) is None
    # A step is read whole, so a reporting name inside a step that also reaches
    # outside the run buys it no reporting reading.
    whole = w(JOB + "      - run: pytest -q\n      - name: coverage\n"
                    "        run: rsync -az coverage/ "
                    "codecov@reports.example.org:/srv/\n")
    assert "reporting-coverage" in whole["signals"], whole
    assert rules.UNRECOGNISED_PRIVILEGED_STEP in whole["signals"], whole
    assert CREDENTIALS_UNCLEAR in whole["flags"], whole
    # The same asymmetry inside a github-script body, where the two readings of
    # the same action pull opposite ways.
    def script(body):
        return w(JOB + "      - run: pytest -q\n"
                       "      - uses: actions/github-script@v7\n"
                       "        with:\n          script: " + body + "\n")
    posts = script("|\n            "
                   "github.rest.issues.createComment({body: 1})")
    assert CREDENTIALS_REPORTING_ONLY in posts["flags"], posts
    # A script assembled somewhere this cannot see cannot be vouched for.
    opaque = script("${{ env.SCRIPT }}")
    assert CREDENTIALS_UNCLEAR in opaque["flags"], opaque
    # Nor can a call that is not a record of what the run found.
    other = script("|\n            "
                   "github.rest.repos.createDispatchEvent({})")
    assert CREDENTIALS_UNCLEAR in other["flags"], other
    # And as a property of every fixture, not only of the one written for it.
    for case, files in sorted(CASES.items()):
        for scope in (PR_SCOPE, REPO_SCOPE):
            sub = classify(files)[scope]
            if set(sub["signals"]) & rules.UNCLEAR_SIGNALS:
                assert CREDENTIALS_REPORTING_ONLY not in sub["flags"], case


def a_privileged_step_that_runs_regardless_reads_as_reporting():
    """The second signal, for the steps whose tool is in no table (which is
    most of them, since the long tail of CI tooling is long). How a step is
    written says what it is for: a step that still runs after the tests failed
    cannot be one the tests needed."""
    p = classify(CASES["reporting-always"])[PR_SCOPE]
    assert "reporting-conditional" in p["signals"], p
    assert CREDENTIALS_REPORTING_ONLY in p["flags"], p

    def step(cond):
        return w(JOB + "      - run: ./test.sh\n      - name: tell\n"
                       "        " + cond + "\n"
                       '        run: curl -X POST -H "Authorization: Bearer '
                       '$NOTIFY_TOKEN" https://example.org/n\n')
    for cond in ["if: always()", "if: failure()", "if: success() || failure()",
                 "if: ${{ always() }}", "continue-on-error: true"]:
        got = step(cond)
        assert "reporting-conditional" in got["signals"], (cond, got)
        assert CREDENTIALS_REPORTING_ONLY in got["flags"], (cond, got)
    # Without the condition the same step says nothing about its purpose, and
    # the honest answer is unclear rather than either reading.
    plain = step("name: tell again")
    assert CREDENTIALS_UNCLEAR in plain["flags"], plain
    # And the shape that reads the condition backwards: a teardown written
    # `if: always()` runs whatever the tests did because the resources have to
    # go away even after a failure, which is the opposite of droppable.
    teardown = w(JOB + "      - run: terraform apply -auto-approve\n"
                       "      - run: pytest -q\n"
                       "      - name: clean up\n        if: always()\n"
                       "        run: terraform destroy -auto-approve\n"
                       "        env:\n"
                       "          TF_TOKEN: ${{ secrets.TF_TOKEN }}\n")
    assert "reporting-conditional" not in teardown["signals"], teardown
    assert CREDENTIALS_UNCLEAR in teardown["flags"], teardown


def the_axis_spans_the_classes_and_alters_none_of_them():
    """Off the ladder, like assumes-toolchain and for a sharper reason: this is
    a question about what a privilege is FOR, and ranking it would turn it into
    a statement about how large the privilege is."""
    axis_values = {CREDENTIALS_REPORTING_ONLY, CREDENTIALS_TEST_TIME,
                   CREDENTIALS_UNCLEAR}
    for v in sorted(axis_values):
        assert v in ASIDE and v not in PRECEDENCE, v
    privilege = (GROUPS[ACTS_ON_FORGE] | GROUPS["writes-outward"]
                 | {"secret-ref"})
    seen, classes = set(), set()
    for case, files in sorted(CASES.items()):
        prof = classify(files)
        for scope in (PR_SCOPE, REPO_SCOPE):
            sub = prof[scope]
            flags = set(sub["flags"])
            axis = flags & axis_values
            assert len(axis) <= 1, (case, flags)
            assert sub["primary"] == next(x for x in PRECEDENCE
                                          if x in flags - axis), case
            # Absent exactly where the scope needs no privilege, which is what
            # makes "absent" readable as an answer rather than as a gap. A
            # boilerplate grant recorded as unused is the one privileged signal
            # that is not a privilege the scope needs, so it is discounted here
            # rather than left to weaken the invariant into nothing.
            needs = set(sub["signals"]) & privilege
            if rules.UNUSED_GRANT in sub["signals"]:
                needs -= rules.BOILERPLATE_GRANTS
            assert bool(axis) == bool(needs), (case, scope, sub)
            seen |= axis
            if axis:
                classes.add(sub["primary"])
    # All three values and more than one primary class, or the axis is pinned
    # by nothing and the claim that it spans the classes is untested.
    assert seen == axis_values, seen
    assert len(classes) > 1, classes


def step_order_can_demote_a_reporting_reading_never_create_one():
    """The weakest signal, and the only one allowed to act in a single
    direction. A coverage upload that runs before any test has not reported on
    one, so the reading is demoted; nothing about where a step sits may ever
    promote it, because order is exactly the kind of weak evidence that would
    hand the flattering answer out for free."""
    upload = ("      - uses: codecov/codecov-action@v4\n        with:\n"
              "          token: ${{ secrets.CODECOV_TOKEN }}\n")
    tests = "      - run: pytest -q --cov\n"
    after = w(JOB + tests + upload)
    assert CREDENTIALS_REPORTING_ONLY in after["flags"], after
    before = w(JOB + upload + tests)
    assert "reporting-coverage" in before["signals"], before
    assert CREDENTIALS_UNCLEAR in before["flags"], before
    assert CREDENTIALS_REPORTING_ONLY not in before["flags"], before
    # With no test invocation to order against, the tiebreak is inert rather
    # than guessing: the tool's name is still the stronger signal.
    alone = w(JOB + upload)
    assert CREDENTIALS_REPORTING_ONLY in alone["flags"], alone


def build_plumbing_consumes_no_privilege_unless_handed_a_secret():
    """The other side of the asymmetry, and the reason it is affordable at all.
    The edge is the whole of the rule: membership of the list must never
    swallow a credential handed to the step.

    Worth reading beside EXPERIMENTS.md, "A failed hypothesis, with a measured
    effect of zero": this list was built to close an uncertainty band and
    changed no number at all. It is kept because the property it states is
    still the right one; what it is not is a fix for the band."""
    wrapped = classify(CASES["neutral-plus-reporting"])[PR_SCOPE]
    assert CREDENTIALS_REPORTING_ONLY in wrapped["flags"], wrapped
    assert not set(wrapped["signals"]) & rules.UNCLEAR_SIGNALS, wrapped
    # The same checkout handed a personal access token is not neutral, so
    # nothing recognises what that secret is for and the scope is unclear.
    handed = classify(CASES["neutral-handed-secret"])[PR_SCOPE]
    assert rules.UNRECOGNISED_PRIVILEGED_STEP in handed["signals"], handed
    assert CREDENTIALS_UNCLEAR in handed["flags"], handed
    assert CREDENTIALS_REPORTING_ONLY not in handed["flags"], handed
    for act in ["actions/checkout@v4", "actions/setup-node@v4",
                "actions/cache/restore@v4", "actions/upload-artifact@v4",
                "actions/download-artifact@v4", "docker/metadata-action@v5",
                "docker/setup-buildx-action@v3", "docker/setup-qemu-action@v3",
                "r-lib/actions/setup-r@v2", "astral-sh/setup-uv@v5"]:
        step = "      - uses: " + act + "\n"
        assert rules.neutral_step(step), act
        assert not rules.neutral_step(
            step + "        with:\n          token: ${{ secrets.PAT }}\n"), act
        assert not rules.neutral_step(
            step + "        env:\n"
                   "          API_KEY: ${{ secrets.API_KEY }}\n"), act
    # And an action the list has never heard of is not neutral by default,
    # which is the direction that keeps the asymmetry intact.
    assert not rules.neutral_step("      - uses: some-org/some-action@v1\n")


def a_grant_nothing_consumes_decides_nothing():
    """A permissions block is copied between workflows constantly and outlives
    the step it was added for, so one that nothing exercises must not hold a
    repository out of the figure on its own. The grants that ARE the evidence
    of a write stay privileges, which is the distinction that keeps this from
    being a blanket amnesty."""
    unused = classify(CASES["unused-permissions-grant"])[PR_SCOPE]
    assert rules.UNUSED_GRANT in unused["signals"], unused
    assert rules.UNUSED_GRANT not in rules.UNCLEAR_SIGNALS
    assert not set(unused["signals"]) & rules.UNCLEAR_SIGNALS, unused
    assert CREDENTIALS_UNCLEAR not in unused["flags"], unused
    for case in ("packages-permission", "id-token-permission"):
        keyless = classify(CASES[case])[PR_SCOPE]
        assert rules.UNATTRIBUTED_PRIVILEGE in keyless["signals"], (case,
                                                                    keyless)
        assert CREDENTIALS_UNCLEAR in keyless["flags"], (case, keyless)
        assert rules.UNUSED_GRANT not in keyless["signals"], (case, keyless)
    # Two shapes where the consumer is merely invisible are refused the reading
    # rather than guessed at: a job that calls a reusable workflow, and a file
    # that names the forge's own token (which is what a permissions block
    # scopes, so every step it is passed to is a plausible consumer).
    def grant(job):
        return w("on:\n  pull_request:\npermissions:\n"
                 "  pull-requests: write\njobs:\n" + job)
    plain = grant("  t:\n    runs-on: ubuntu-latest\n    steps:\n"
                  "      - run: pytest -q\n")
    assert rules.UNUSED_GRANT in plain["signals"], plain
    called = grant("  t:\n    uses: ./.github/workflows/reusable.yml\n")
    assert rules.UNUSED_GRANT not in called["signals"], called
    assert CREDENTIALS_UNCLEAR in called["flags"], called
    tokened = grant("  t:\n    runs-on: ubuntu-latest\n    steps:\n"
                    "      - uses: some-org/labeler@v1\n        with:\n"
                    "          token: ${{ secrets.GITHUB_TOKEN }}\n")
    assert rules.UNUSED_GRANT not in tokened["signals"], tokened
    assert CREDENTIALS_UNCLEAR in tokened["flags"], tokened


def cloud_authentication_is_test_time_and_an_app_mint_is_forge_side():
    """Two privileged steps a corpus census surfaced and no table named. Cloud
    authentication is real privilege and plainly not a record of the run, so
    the axis answers rather than shrugs; an App token mint is forge-side
    privilege, and there the honest answer stays unclear, because the mint says
    what the token can do and never what it is for."""
    cloud = classify(CASES["cloud-credential"])[PR_SCOPE]
    assert rules.CLOUD_CREDENTIAL in cloud["signals"], cloud
    assert rules.CLOUD_CREDENTIAL in rules.TEST_TIME_SIGNALS
    assert CREDENTIALS_TEST_TIME in cloud["flags"], cloud
    assert contributor_runnable(
        {"o/r": classify(CASES["cloud-credential"])})[0] == 0
    app = classify(CASES["forge-app-token"])[PR_SCOPE]
    assert "forge-app-token" in app["signals"], app
    assert "forge-app-token" in GROUPS[ACTS_ON_FORGE]
    assert app["primary"] == ACTS_ON_FORGE, app
    assert CREDENTIALS_UNCLEAR in app["flags"], app

    def cloudjob(auth, tail):
        return w(JOB + "      - uses: " + auth + "\n        with:\n"
                       "          creds: ${{ secrets.CLOUD }}\n" + tail)
    for auth in ["aws-actions/configure-aws-credentials@v4",
                 "aws-actions/amazon-ecr-login@v2", "azure/login@v2",
                 "google-github-actions/auth@v2"]:
        tested = cloudjob(auth, "      - run: pytest -q tests/integration\n")
        assert CREDENTIALS_TEST_TIME in tested["flags"], (auth, tested)
        # No test after the authentication: the credential is the deploy's, and
        # saying test-time there would be the wrong label on a scope the figure
        # excludes either way.
        deployed = cloudjob(auth, "      - run: ./scripts/deploy.sh\n")
        assert rules.CLOUD_CREDENTIAL not in deployed["signals"], (auth,
                                                                   deployed)
        assert CREDENTIALS_UNCLEAR in deployed["flags"], (auth, deployed)
        # Nor does it fire where the file spends the credential outward.
        spent = cloudjob(auth, "      - run: pytest -q\n"
                               "      - run: aws s3 sync out/ s3://bucket/\n")
        assert rules.CLOUD_CREDENTIAL not in spent["signals"], (auth, spent)


def the_flush_steps_block_is_attributed():
    """The fixture for the measured parser defect, read through the axis: with
    the steps attributed, the one credential feeds a code-quality upload and
    the scope is reporting-only. Read as an empty block it was an
    unattributable privilege instead."""
    flush = classify(CASES["steps-at-key-column"])[PR_SCOPE]
    assert CREDENTIALS_REPORTING_ONLY in flush["flags"], flush
    assert not set(flush["signals"]) & rules.UNCLEAR_SIGNALS, flush


sys.exit(run([
    ("a secret that only feeds a reporting step is reporting-only, and counted",
     a_secret_that_only_feeds_a_reporting_step_is_counted),
    ("a dependency-resolution credential is test-time, and not counted",
     a_dependency_resolution_credential_is_test_time),
    ("one unrecognised privileged step is enough to deny reporting-only",
     one_unrecognised_privileged_step_denies_reporting_only),
    ("a privileged step that runs regardless reads as reporting",
     a_privileged_step_that_runs_regardless_reads_as_reporting),
    ("the axis spans the classes and alters none of them",
     the_axis_spans_the_classes_and_alters_none_of_them),
    ("step order can demote a reporting reading, never create one",
     step_order_can_demote_a_reporting_reading_never_create_one),
    ("build plumbing consumes no privilege, unless it is handed a secret",
     build_plumbing_consumes_no_privilege_unless_handed_a_secret),
    ("a grant nothing consumes decides nothing, and self-evident grants do",
     a_grant_nothing_consumes_decides_nothing),
    ("cloud authentication is test-time, and an App token mint is forge-side",
     cloud_authentication_is_test_time_and_an_app_mint_is_forge_side),
    ("a steps: block at its own column is attributed, so the axis can answer",
     the_flush_steps_block_is_attributed),
]))
