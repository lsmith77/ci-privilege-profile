#!/usr/bin/env python3
"""The test-step determination: does the suite itself consume a credential?

The credentials axis next door asks whether EVERY privileged step in a scope is
droppable, and one step nothing recognised holds the whole scope unclear. This
asks a narrower question, and these checks exist because the narrower question
has three ways to be answered flatteringly and wrongly:

  - by ignoring inherited environment, which is the trap. A job-level `env:` is
    the ordinary way to hand a whole job a credential, so a reading that looked
    only at the step's own text would be wrong in bulk and in the flattering
    direction.
  - by reading a step the enclosing scope could not be cut out of as clean.
  - by reading an unrecognised command as a test invocation that needs nothing.

Each has a check below, and each is worth mutating: the rule that holds the
flattering answer back is invisible in the output when it stops working.
"""
import sys

import harness
from harness import run

harness.offline()

from ciprofile import rules, structure                            # noqa: E402
from ciprofile.classify import (ASIDE, PRECEDENCE, PR_SCOPE,      # noqa: E402
                                REPO_SCOPE, TEST_STEP_PRIVILEGED,
                                TEST_STEP_UNIDENTIFIED,
                                TEST_STEP_UNPRIVILEGED, classify,
                                tests_unprivileged)
from ciprofile.fixtures import fixture_cases                      # noqa: E402

CASES = fixture_cases()
JOB = ("on:\n  pull_request:\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
       "    steps:\n")


def w(body, scope=PR_SCOPE):
    return classify({".github/workflows/w.yml": body})[scope]


def gl(body, scope=PR_SCOPE):
    return classify({".gitlab-ci.yml": body})[scope]


def an_inherited_credential_is_available_to_the_test_step():
    """THE TRAP, and the one failure here that would be wrong in bulk rather
    than at the margin. A credential mapped in at workflow level or job level
    `env:` is in the environment of every step in that scope, the test step
    included, although the step itself names no secret. GitLab's global and job
    `variables:` behave the same way.

    Note what the credentials axis says about the same fixture: the privilege
    sits in the frame, where no step can be held responsible for it, so that
    axis reads `unattributed-privilege`. The two readings are asked of
    different units, which is exactly why this determination needed its own
    segmentation rather than the frame privilege_units() already returned."""
    p = classify(CASES["test-step-inherited-env"])[PR_SCOPE]
    assert rules.TEST_STEP_INHERITED_CREDENTIAL in p["signals"], p
    assert TEST_STEP_PRIVILEGED in p["flags"], p
    assert rules.UNATTRIBUTED_PRIVILEGE in p["signals"], p
    # Both levels, and both grammars.
    job_level = w("on:\n  pull_request:\njobs:\n  t:\n"
                  "    runs-on: ubuntu-latest\n    env:\n"
                  "      DB_PASSWORD: ${{ secrets.DB }}\n"
                  "    steps:\n      - run: pytest -q\n")
    assert TEST_STEP_PRIVILEGED in job_level["flags"], job_level
    flow_level = w("on:\n  pull_request:\nenv:\n"
                   "  DB_PASSWORD: ${{ secrets.DB }}\n"
                   "jobs:\n  t:\n    runs-on: ubuntu-latest\n"
                   "    steps:\n      - run: pytest -q\n")
    assert rules.TEST_STEP_INHERITED_CREDENTIAL in flow_level["signals"], \
        flow_level
    assert TEST_STEP_PRIVILEGED in flow_level["flags"], flow_level
    globals_ = gl("variables:\n  REGISTRY_PASSWORD: $CI_REGISTRY_PASSWORD\n"
                  "test:\n  script:\n    - pytest -q\n")
    assert rules.TEST_STEP_INHERITED_CREDENTIAL in globals_["signals"], globals_
    assert TEST_STEP_PRIVILEGED in globals_["flags"], globals_
    # A GitLab job's own `variables:` are inside the unit rather than enclosing
    # it, because the unit there IS the job. Same verdict, different evidence,
    # and the evidence is what says which reading found it.
    job_vars = gl("test:\n  variables:\n    API_TOKEN: $SECRET_API_TOKEN\n"
                  "  script:\n    - pytest -q\n")
    assert rules.TEST_STEP_CREDENTIAL in job_vars["signals"], job_vars
    assert TEST_STEP_PRIVILEGED in job_vars["flags"], job_vars


def a_credential_in_another_job_does_not_reach_this_one():
    """What the new segmentation buys, and the reason the frame
    privilege_units() returns could not be reused. That frame is one text for
    the whole file, so a credential in the publish job's `env:` sits in the
    same frame as the test job's steps and would read as available to them.
    Scoped per step, it does not: the test job inherits the workflow's own keys
    and its own job's keys, and nothing from a sibling.

    Without this the determination would be a restatement of "does this file
    hold a credential anywhere", which is the ladder's question and already
    answered."""
    two_jobs = ("on:\n  pull_request:\njobs:\n"
                "  publish:\n    runs-on: ubuntu-latest\n    env:\n"
                "      NPM_TOKEN: ${{ secrets.NPM_TOKEN }}\n"
                "    steps:\n      - run: npm publish\n"
                "  test:\n    runs-on: ubuntu-latest\n"
                "    steps:\n      - run: pytest -q\n")
    sibling = w(two_jobs)
    assert rules.TEST_STEP_CLEAN in sibling["signals"], sibling
    assert TEST_STEP_UNPRIVILEGED in sibling["flags"], sibling
    assert rules.TEST_STEP_INHERITED_CREDENTIAL not in sibling["signals"], \
        sibling
    # And the segmentation itself, stated directly: each step is handed the
    # scopes enclosing IT, so the publish job's `env:` is in that job's step's
    # scope and in no other. Stated for both readings, because only one of them
    # is installed at a time and the other is what most environments run.
    saved = structure._yaml
    try:
        for reading in (saved, None):
            structure._yaml = reading
            pairs = structure.units_with_scope("actions", two_jobs)
            assert len(pairs) == 2, (reading, pairs)
            assert [n for n, (_u, s) in enumerate(pairs)
                    if "NPM_TOKEN" in s] == [0], (reading, pairs)
            assert TEST_STEP_UNPRIVILEGED in w(two_jobs)["flags"], reading
    finally:
        structure._yaml = saved


def a_clean_test_step_beside_a_later_credential_is_unprivileged():
    """The case the determination exists for, and the reading the credentials
    axis cannot reach: the only credential is the publish step's, so the tests
    run without it, while that publish is a privileged step recognised as
    neither reporting nor test-time and therefore holds the whole scope
    unclear. Both answers are correct about their own question."""
    p = classify(CASES["test-step-clean-publish-later"])[PR_SCOPE]
    assert rules.TEST_STEP_CLEAN in p["signals"], p
    assert TEST_STEP_UNPRIVILEGED in p["flags"], p
    assert rules.CREDENTIALS_UNCLEAR in p["flags"], p
    # The same shape over the whole fixture corpus: wherever the determination
    # answers unprivileged, the credentials axis is free to say anything, and
    # that is the point of having both.
    verdicts = set()
    for case, files in sorted(CASES.items()):
        sub = classify(files)[PR_SCOPE]
        if TEST_STEP_UNPRIVILEGED in sub["flags"]:
            verdicts |= set(sub["flags"]) & {rules.CREDENTIALS_UNCLEAR,
                                             rules.CREDENTIALS_REPORTING_ONLY}
    assert verdicts == {rules.CREDENTIALS_UNCLEAR,
                        rules.CREDENTIALS_REPORTING_ONLY}, verdicts


def a_compound_command_is_read_whole():
    """A test invocation sharing a shell line with a privileged act is a
    privileged step, and installing alongside one is not. The unit a rule asks
    of is the whole step, which is what settles it: a reading that cut shell
    lines apart would have to decide which half of a `&&` a credential belongs
    to, and the answer is both."""
    p = classify(CASES["test-step-login-and-test"])[PR_SCOPE]
    assert rules.TEST_STEP_CREDENTIAL in p["signals"], p
    assert TEST_STEP_PRIVILEGED in p["flags"], p
    # The act alone, with no credential-shaped name anywhere: the password
    # arrives on stdin, so the name scan sees nothing and the login itself is
    # the evidence. This is the half that is not an accident of the variable
    # name, and the half a mutation of STEP_AUTHENTICATES must break.
    stdin = w(JOB + "      - run: docker login registry.example.org -u ci "
                    "--password-stdin < /run/pw && npm test\n")
    assert not rules.credential_names(
        "docker login registry.example.org -u ci --password-stdin < /run/pw")
    assert rules.TEST_STEP_PRIVILEGED_ACT in stdin["signals"], stdin
    assert TEST_STEP_PRIVILEGED in stdin["flags"], stdin
    # And the converse, which matters as much: an install is not a privilege.
    install = w(JOB + "      - run: npm ci && npm test\n")
    assert rules.TEST_STEP_CLEAN in install["signals"], install
    assert TEST_STEP_UNPRIVILEGED in install["flags"], install
    # Nor is a lint or a build sharing the line.
    plain = w(JOB + "      - run: npm run lint && npm run build && npm test\n")
    assert TEST_STEP_UNPRIVILEGED in plain["flags"], plain
    # A privileged act that is not an authentication counts too: a step that
    # runs the tests and then pushes an image consumes whatever the push needs.
    pushes = w(JOB + "      - run: go test ./... && docker push ex.org/a:1\n")
    assert rules.TEST_STEP_PRIVILEGED_ACT in pushes["signals"], pushes
    assert TEST_STEP_PRIVILEGED in pushes["flags"], pushes


def the_forge_minted_token_is_not_a_credential_and_says_so():
    """Consistent with the carve-out on the ladder: the forge mints these, so a
    contributor supplies nothing for them and a test step reached by one and
    nothing else runs unprivileged. Recorded as its own evidence rather than
    folded in, so the size of the judgement can be re-sliced here as
    `uses-forge-token` lets it be re-sliced there."""
    p = classify(CASES["test-step-forge-token-only"])[PR_SCOPE]
    assert rules.TEST_STEP_FORGE_TOKEN in p["signals"], p
    assert rules.TEST_STEP_CLEAN in p["signals"], p
    assert TEST_STEP_UNPRIVILEGED in p["flags"], p
    assert rules.TEST_STEP_FORGE_TOKEN not in rules.TEST_STEP_PRIVILEGED_SIGNALS
    # Every token in the carve-out, inherited and named directly, in whichever
    # grammar it occurs in. One list of forge tokens, consulted here and by the
    # ladder, so the two can never drift.
    for name in sorted(rules.FORGE_TOKENS):
        inherited = w("on:\n  pull_request:\njobs:\n  t:\n"
                      "    runs-on: ubuntu-latest\n    env:\n"
                      "      T: ${{ secrets." + name + " }}\n"
                      "    steps:\n      - run: pytest -q\n")
        assert rules.TEST_STEP_FORGE_TOKEN in inherited["signals"], name
        assert TEST_STEP_UNPRIVILEGED in inherited["flags"], (name, inherited)
        own = w(JOB + "      - run: pytest -q\n        env:\n"
                      "          T: ${{ secrets." + name + " }}\n")
        assert TEST_STEP_UNPRIVILEGED in own["flags"], (name, own)
    # And a real secret beside the forge token is still a real secret, which is
    # what keeps the carve-out from being an amnesty.
    both = w("on:\n  pull_request:\njobs:\n  t:\n"
             "    runs-on: ubuntu-latest\n    env:\n"
             "      T: ${{ secrets.GITHUB_TOKEN }}\n"
             "      K: ${{ secrets.DEPLOY_KEY }}\n"
             "    steps:\n      - run: pytest -q\n")
    assert rules.TEST_STEP_FORGE_TOKEN in both["signals"], both
    assert rules.TEST_STEP_INHERITED_CREDENTIAL in both["signals"], both
    assert TEST_STEP_PRIVILEGED in both["flags"], both


def an_unrecognised_command_is_not_identifiable_rather_than_clean():
    """RECOGNITION, NOT INFERENCE, and the error direction that follows from
    it. Nothing here reads an unfamiliar command and decides it looks like a
    test run, so a project's own shell script answers "not identifiable".

    The direction matters both ways and is why the list is kept to command
    forms that mean a test run and nothing else: a MISSED form costs a reading,
    while a SPURIOUS match on a clean step would hand out the flattering
    answer for free."""
    p = classify(CASES["test-step-unknown-runner"])[PR_SCOPE]
    assert not set(p["signals"]) & rules.TEST_STEP_SIGNALS, p
    assert TEST_STEP_UNIDENTIFIED in p["flags"], p
    for unknown in ["./ci/run-acceptance.sh --suite smoke",
                    "bundle exec cucumber", "robot --outputdir out tests/",
                    "./gradlew assemble", "npm run build", "npm ci",
                    "mvn -B package -DskipTests", "cmake --build build",
                    "flake8 src/", "echo testing"]:
        got = w(JOB + "      - run: " + unknown + "\n")
        assert TEST_STEP_UNIDENTIFIED in got["flags"], (unknown, got)
    # Every form on the list is matched by it. A dead alternative in a long
    # regex reads as a decision nothing enforces, exactly as a dead entry in an
    # exception list does.
    for cmd in ["pytest -q", "tox -e py312", "nox -s tests", "npm test",
                "yarn test", "pnpm run test", "bun test", "go test ./...",
                "cargo test --all", "dotnet test", "ctest --output-on-failure",
                "mvn -B verify", "mvn test", "./gradlew test", "gradle check",
                "make test", "just check", "rake test", "invoke test",
                "task test", "ant -noinput -buildfile build.xml test",
                "phpunit", "bundle exec rspec", "npx jest",
                "vitest run", "mocha", "bats tests/", "python3 -m pytest",
                "python -m unittest discover", "behave", "playwright test",
                "Rscript -e 'devtools::test()'",
                # the additions
                "py.test -q", "gotestsum --format short", "ginkgo -r",
                "cargo nextest run", "composer test", "composer run test",
                "mix test", "sbt ++2.13 test", "dune runtest", "dune test",
                "swift test", "deno test -A", "flutter test", "dart test",
                "meson test -C build", "ninja test", "cabal test",
                "stack test", "cypress run", "zig build test",
                "R CMD check ."]:
        assert rules.TEST_INVOCATION.search(cmd), cmd
        got = w(JOB + "      - run: " + cmd + "\n")
        assert TEST_STEP_UNPRIVILEGED in got["flags"], (cmd, got)


def an_undeterminable_scope_is_privileged_not_clean():
    """THE ERROR DIRECTION, stated over every combination rather than over one
    shape. Where whether a credential reaches the test step cannot be settled,
    the step is privileged: the flattering answer must never win by default,
    which is the same asymmetry credentials_purpose() enforces. Reverse it and
    every file this cannot segment, and every GitLab file whose variables come
    from an `include:`, would be counted as a test suite that runs
    unprivileged."""
    for extra in [set(), {rules.TEST_STEP_CLEAN},
                  {rules.TEST_STEP_FORGE_TOKEN},
                  {rules.TEST_STEP_CLEAN, rules.TEST_STEP_FORGE_TOKEN}]:
        for blocker in sorted(rules.TEST_STEP_PRIVILEGED_SIGNALS):
            got = rules.test_step_privilege(extra | {blocker})
            assert got == TEST_STEP_PRIVILEGED, (extra, blocker, got)
        for timed in sorted(rules.TEST_TIME_SIGNALS):
            got = rules.test_step_privilege(extra | {timed})
            assert got == TEST_STEP_PRIVILEGED, (extra, timed, got)
    assert rules.test_step_privilege({rules.TEST_STEP_CLEAN}) \
        == TEST_STEP_UNPRIVILEGED
    assert rules.test_step_privilege(set()) == TEST_STEP_UNIDENTIFIED
    assert rules.test_step_privilege({rules.TEST_STEP_FORGE_TOKEN}) \
        == TEST_STEP_UNIDENTIFIED
    # A GitLab file that is not the whole configuration: an `include:` carries
    # another file's global `variables:` and `extends:` another job's, so a
    # credential could reach the test step from text that was never fetched.
    # Ordinary GitLab style rather than an edge, which is why the refusal is
    # recorded as its own signal: the cost of the rule stays countable.
    for head in ["include:\n  - local: /ci/base.yml\n",
                 "include:\n  - project: g/ci\n    file: /base.yml\n"]:
        inc = gl(head + "test:\n  script:\n    - pytest -q\n")
        assert rules.TEST_STEP_SCOPE_INCOMPLETE in inc["signals"], inc
        assert TEST_STEP_PRIVILEGED in inc["flags"], inc
    ext = gl("test:\n  extends: .base\n  script:\n    - pytest -q\n")
    assert rules.TEST_STEP_SCOPE_INCOMPLETE in ext["signals"], ext
    assert TEST_STEP_PRIVILEGED in ext["flags"], ext
    # And a GitLab file that is whole still answers.
    whole = gl("test:\n  image: python:3.12\n  script:\n    - pytest -q\n")
    assert rules.TEST_STEP_CLEAN in whole["signals"], whole
    assert TEST_STEP_UNPRIVILEGED in whole["flags"], whole
    # A step whose enclosing scope could not be cut out of the file at all. The
    # line reader's own refusal, forced here because it is the reading most
    # environments run: it finds `jobs:` by the written key, so a quoted one
    # leaves the step unplaceable, and an unplaceable step is handed back with
    # no scope rather than dropped. Dropping it would be the flattering
    # direction, since a step nobody looks at consumes nothing.
    quoted = ('"jobs":\n  t:\n    runs-on: ubuntu-latest\n'
              '    steps:\n      - run: pytest -q\n')
    saved = structure._yaml
    structure._yaml = None
    try:
        pairs = structure.units_with_scope("actions", quoted)
        assert pairs and all(s is None for _u, s in pairs), pairs
        assert rules.test_step_signals("actions", quoted) \
            == {rules.TEST_STEP_SCOPE_UNREADABLE}
        assert TEST_STEP_PRIVILEGED in w(quoted)["flags"]
    finally:
        structure._yaml = saved


def the_determination_spans_the_classes_and_alters_none_of_them():
    """Off the ladder, for the same reason the credentials axis is: this asks
    what a privilege is FOR, and ranking it would turn it into a statement
    about how large the privilege is. Present wherever a scope holds a pipeline
    file and absent wherever it holds none, which is what makes each value
    readable as an answer rather than as a gap."""
    values = {TEST_STEP_UNPRIVILEGED, TEST_STEP_PRIVILEGED,
              TEST_STEP_UNIDENTIFIED}
    for v in sorted(values):
        assert v in ASIDE and v not in PRECEDENCE, v
    seen, classes = set(), set()
    for case, files in sorted(CASES.items()):
        prof = classify(files)
        for scope in (PR_SCOPE, REPO_SCOPE):
            sub = prof[scope]
            flags = set(sub["flags"])
            mine = flags & values
            assert len(mine) <= 1, (case, flags)
            # Struck out, the ladder answers exactly the same thing.
            assert sub["primary"] == next(x for x in PRECEDENCE
                                          if x in flags - mine), case
            assert bool(mine) == bool(sub["files"]), (case, scope, sub)
            seen |= mine
            if mine:
                classes.add(sub["primary"])
    assert seen == values, seen
    assert len(classes) > 1, classes


def the_derived_figure_is_reported_with_its_band():
    """The figure the determination exists for, and the count of scopes whose
    test invocation nothing could find beside it. A test suite this could not
    find is not a test suite that needs nothing, so the band belongs to the
    answer in exactly the way the unclear count belongs to
    contributor_runnable()'s."""
    import contextlib
    import io
    repos = {c: classify(f) for c, f in CASES.items()}
    clean, privileged, unidentified = tests_unprivileged(repos)
    assert clean and privileged and unidentified, (clean, privileged,
                                                   unidentified)
    with_pipeline = sum(1 for p in repos.values() if p[PR_SCOPE]["files"])
    assert clean + privileged + unidentified == with_pipeline
    from ciprofile import report
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report.report({}, repos, {})
    said = out.getvalue()
    width = max(len(x) for x in PRECEDENCE + ASIDE)
    for want in ["  %s  %5d" % ("with a test suite that runs unprivileged"
                                .ljust(width), clean),
                 "vs %d whose test step has a credential available to it"
                 % privileged,
                 "and %d where no test invocation could be" % unidentified,
                 "this figure's band"]:
        assert want in said, (want, said)
    # And in the file, which is what outlives the terminal.
    import json
    import os
    import tempfile
    got = json.load(open(report.write(
        os.path.join(tempfile.mkdtemp(), report.PROFILE_NAME), repos, {})))
    assert got["tests_unprivileged"][PR_SCOPE] == {
        "repos": clean, "privileged": privileged,
        "unidentified": unidentified}, got["tests_unprivileged"]
    assert REPO_SCOPE in got["tests_unprivileged"]
    assert "test-step-unprivileged" in got["$comment"]
    assert "inheritance" in got["$comment"]


sys.exit(run([
    ("an inherited credential is available to the test step",
     an_inherited_credential_is_available_to_the_test_step),
    ("a credential in another job does not reach this one",
     a_credential_in_another_job_does_not_reach_this_one),
    ("a clean test step beside a later credential is unprivileged",
     a_clean_test_step_beside_a_later_credential_is_unprivileged),
    ("a compound command is read whole, and installing is not a privilege",
     a_compound_command_is_read_whole),
    ("the forge-minted token is not a credential, and says so separately",
     the_forge_minted_token_is_not_a_credential_and_says_so),
    ("an unrecognised command is not identifiable, never clean",
     an_unrecognised_command_is_not_identifiable_rather_than_clean),
    ("an undeterminable scope is privileged, never clean",
     an_undeterminable_scope_is_privileged_not_clean),
    ("the determination spans the classes and alters none of them",
     the_determination_spans_the_classes_and_alters_none_of_them),
    ("the derived figure is reported with its band",
     the_derived_figure_is_reported_with_its_band),
]))
