#!/usr/bin/env python3
"""The ladder, the scopes, and the rules whose error direction moves a figure.

Every check here is a defect that happened. Where one is a measured one the
comment carries the measurement, because that is what says how much the rule is
worth.
"""
import sys

import harness
from harness import run

harness.offline()

from ciprofile import rules                                      # noqa: E402
from ciprofile.classify import (ACTS_ON_FORGE, ASIDE,            # noqa: E402
                                ASSUMES_TOOLCHAIN, GROUPS,
                                NO_PIPELINE, NO_PULL_REQUEST_TRIGGER,
                                PRECEDENCE, PR_SCOPE, PULL_REQUEST_TARGET,
                                READ_CREDENTIAL, REPO_SCOPE, SELF_CONTAINED,
                                SPECIAL_ENV, THIN_WRAPPER, USES_FORGE_TOKEN,
                                WRITES_OUTWARD, classify)
from ciprofile.fixtures import fixture_cases                     # noqa: E402
from ciprofile.structure import (actions_commands, actions_steps,  # noqa: E402
                                 actions_triggers,
                                 in_pull_request_scope)

STEPS = "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"


def f(body, scope=REPO_SCOPE):
    return classify({".github/workflows/w.yml": body})[scope]


def release_workflow_stays_out_of_the_pull_request_scope():
    """The smallest case the scoping exists for.

    Measured failure before it existed: a repository whose pull-request check
    was pure lint classified as writes-outward because an unrelated release
    workflow ran `npm publish`. Nearly every mature project carries such a
    workflow, so the error was in bulk rather than at the margin.
    """
    pr = ("name: ci\non:\n  pull_request:\n\njobs:\n  lint:\n"
          "    runs-on: ubuntu-latest\n    steps:\n      - run: ./lint.sh\n")
    rel = ("name: release\non:\n  push:\n    tags: [v1]\n\njobs:\n  publish:\n"
           "    runs-on: ubuntu-latest\n    steps:\n"
           "      - run: npm ci && npm publish\n")
    alone = classify({".github/workflows/ci.yml": pr})
    both = classify({".github/workflows/ci.yml": pr,
                     ".github/workflows/release.yml": rel})
    # Adding the release workflow must not move the pull-request reading at all.
    assert alone[PR_SCOPE] == both[PR_SCOPE], (alone, both)
    assert both[PR_SCOPE]["primary"] == SELF_CONTAINED, both
    assert both[REPO_SCOPE]["primary"] == WRITES_OUTWARD, both
    # thin-wrapper is computed in the scope for the same reason: it dies on the
    # first non-thin command, so the release workflow's `&&` would otherwise
    # take it off a one-line pull-request check.
    assert THIN_WRAPPER in both[PR_SCOPE]["flags"], both
    assert THIN_WRAPPER not in both[REPO_SCOPE]["flags"], both
    # Nor may its signals leak, since the signals are the evidence a reader
    # re-slices the labels from.
    assert both[PR_SCOPE]["signals"] == [], both
    assert "package-publish" in both[REPO_SCOPE]["signals"], both
    assert both[PR_SCOPE]["files"] == [".github/workflows/ci.yml"], both
    assert len(both[REPO_SCOPE]["files"]) == 2, both


def a_pipeline_no_pull_request_triggers_is_its_own_state():
    """Having a pipeline and having one a contributor can set off are
    different facts. Folding the second into no-pipeline would say the project
    does no CI, inflating one of the figures most likely to be quoted."""
    rel = classify({".github/workflows/release.yml":
                    "on:\n  push:\n    tags: [v1]\njobs:\n  p:\n"
                    "    runs-on: ubuntu-latest\n    steps:\n"
                    "      - run: twine upload dist/x\n"})
    assert rel[PR_SCOPE]["primary"] == NO_PULL_REQUEST_TRIGGER, rel
    # The pipeline is still a real requirement on whoever cuts the release.
    assert rel[REPO_SCOPE]["primary"] == WRITES_OUTWARD, rel
    empty = classify({})
    for scope in (PR_SCOPE, REPO_SCOPE):
        assert empty[scope]["primary"] == NO_PIPELINE, empty
    # Below self-contained, above no-pipeline: a scope that holds files it
    # cannot run is nearer to having a pipeline than to having none.
    assert (PRECEDENCE.index(SELF_CONTAINED)
            < PRECEDENCE.index(NO_PULL_REQUEST_TRIGGER)
            < PRECEDENCE.index(NO_PIPELINE)), PRECEDENCE


def the_on_shapes_parse_and_an_unreadable_one_is_in_scope():
    """Reading `on:` is what the whole scope split rests on, and an unhandled
    shape is silent: it reads as undeterminable, which puts the file in scope
    and keeps a privileged workflow in the quoted figure rather than hiding it.
    """
    jobs = ("\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: ./a.sh\n")
    shapes = [
        ("on: [push, pull_request]", {"push", "pull_request"}),
        ("on: pull_request", {"pull_request"}),
        ("on:\n  push:\n  pull_request:", {"push", "pull_request"}),
        ("on:\n  pull_request:\n    types: [opened, synchronize]",
         {"pull_request"}),
        ("on:\n  - push\n  - pull_request", {"push", "pull_request"}),
        ("on: {pull_request: null}", {"pull_request"}),
        ("on: push  # only pushes", {"push"}),
        # YAML 1.1 reads a bare `on` as a boolean, so emitters quote it.
        ('"on":\n  pull_request:', {"pull_request"}),
    ]
    for text, want in shapes:
        got = actions_triggers(text + jobs)
        assert got == want, (text, "read as", got, "wanted", want)
    # Undeterminable is not "no triggers". It is in scope, deliberately.
    assert actions_triggers("name: ci" + jobs) is None
    # Top level only: an `on:` inside a `with:` block is an action input.
    nested = actions_triggers(
        "on:\n  push:\njobs:\n  a:\n    steps:\n      - uses: x/y\n"
        "        with:\n          on: pull_request\n")
    assert nested == {"push"}, nested
    scoped = [
        (".github/workflows/a.yml", "jobs:\n  a:\n", True),
        (".github/workflows/a.yml", "on: push" + jobs, False),
        (".github/workflows/a.yml", "on: pull_request_target" + jobs, True),
        # A reusable workflow cannot say who calls it, so it stays visible.
        (".github/workflows/a.yml", "on:\n  workflow_call:" + jobs, True),
        # A GitLab file is in scope whole: job-level reachability on a merge
        # request needs more than one file's text.
        (".gitlab-ci.yml", "build:\n  script:\n    - make\n", True),
    ]
    for path, text, want in scoped:
        got = in_pull_request_scope(path, text)
        assert got == want, (path, text, "in scope", got, "wanted", want)


def pull_request_target_is_read_off_the_on_declaration_only():
    """One of the few figures exact enough to quote outside, so it is held to
    the trigger. The bare word reads the same in a `run:` step, a URL or a doc
    path, and every one of those over-claims a privileged trigger."""
    declared = classify({".github/workflows/a.yml":
                         "on:\n  pull_request_target:\n    types: [opened]\n"
                         + STEPS + "      - run: ./a.sh\n"})
    mentioned = classify({".github/workflows/b.yml":
                          "on:\n  pull_request:\n" + STEPS
                          + "      - run: ./check.sh "
                            "docs/pull_request_target.md\n"})
    url = classify({".github/workflows/c.yml":
                    "on:\n  push:\n" + STEPS
                    + "      - run: curl "
                      "https://example.org/pull_request_target\n"})
    for scope in (PR_SCOPE, REPO_SCOPE):
        assert PULL_REQUEST_TARGET in declared[scope]["flags"], declared
        assert "pull-request-target" in declared[scope]["signals"], declared
        for other in (mentioned, url):
            assert PULL_REQUEST_TARGET not in other[scope]["flags"], other
            assert "pull-request-target" not in other[scope]["signals"], other
    # And the trigger still ranks nothing, which is why it is tallied apart.
    assert declared[PR_SCOPE]["primary"] == SELF_CONTAINED, declared
    assert PULL_REQUEST_TARGET in ASIDE
    assert PULL_REQUEST_TARGET not in PRECEDENCE


def a_toolchain_assumption_is_recorded_and_ranks_nothing():
    """`self-contained` means no secret, no outward write, no runner label. It
    does not mean the job would start on a bare container, and quoting it as if
    it did is the confusion this flag exists to prevent."""
    tc = classify({".github/workflows/w.yml":
                   "on: [pull_request]\njobs:\n  t:\n"
                   "    runs-on: ubuntu-latest\n"
                   "    steps:\n      - uses: actions/setup-node@v4\n"
                   "      - run: npm test\n"})
    for scope in (PR_SCOPE, REPO_SCOPE):
        p = tc[scope]
        assert "toolchain-node" in p["signals"], p
        assert ASSUMES_TOOLCHAIN in p["flags"], p
        # Still self-contained: node being preinstalled on a hosted runner is a
        # bill, not a permission anybody has to grant.
        assert p["primary"] == SELF_CONTAINED, p
        assert p["primary"] == next(x for x in PRECEDENCE if x in
                                    set(p["flags"]) - {ASSUMES_TOOLCHAIN}), p
    assert ASSUMES_TOOLCHAIN in ASIDE and ASSUMES_TOOLCHAIN not in PRECEDENCE
    # The setup family as a family, so a new member needs no table edit.
    for tool in ("python", "java", "go", "dotnet"):
        got = classify({".github/workflows/w.yml":
                        "on: [pull_request]\njobs:\n  t:\n    steps:\n"
                        "      - uses: actions/setup-" + tool + "@v5\n"})
        assert "toolchain-" + tool in got[PR_SCOPE]["signals"], (tool, got)
    # And an image a job names, which is the same statement by other means.
    img = classify({".gitlab-ci.yml":
                    "image: python:3.12\nbuild:\n  script:\n    - make\n"})
    assert "toolchain-image" in img[PR_SCOPE]["signals"], img
    # Off the ladder structurally, not just by convention: no toolchain signal
    # may sit in a group that decides a primary class.
    grouped = set().union(*GROUPS.values())
    assert not [g for g in grouped
                if g.startswith(rules.TOOLCHAIN_PREFIX)], grouped


def an_ordinary_key_variable_is_not_read_as_a_credential():
    """The name scan is the only evidence there is for a credential referenced
    as a plain shell variable, and `_KEY` is where it misfires: cache keys,
    sort keys and idempotency keys are spelled exactly like secrets. Each false
    positive costs a repository its `self-contained` class and lands it in
    `read-credential`, moving the one figure the tool exists to produce."""
    def v(var):
        prof = classify({".github/workflows/w.yml":
                         STEPS + "      - run: echo $" + var + "\n"})
        # These declare no trigger, so the file is in scope and both profiles
        # are the same reading: this is the name scan, not the scope.
        assert prof[PR_SCOPE] == prof[REPO_SCOPE], prof
        return prof[REPO_SCOPE]
    cache = v("CACHE_KEY")
    assert "secret-ref" not in cache["signals"], cache
    assert cache["primary"] == SELF_CONTAINED, cache
    for name in sorted(rules.NOT_CREDENTIAL):
        # A dead entry would read as a decision that had been taken and is not
        # being enforced by anything.
        assert rules.CREDENTIALISH.search(name), name
        assert "secret-ref" not in v(name)["signals"], name
    for name in ["API_KEY", "SSH_KEY", "GPG_KEY", "DEPLOY_KEY", "SIGNING_KEY",
                 "PRIVATE_KEY", "AWS_SECRET_ACCESS_KEY", "NPM_TOKEN",
                 "DB_PASSWORD", "SONAR_TOKEN", "REGISTRY_CREDENTIALS"]:
        assert name not in rules.NOT_CREDENTIAL, name
        got = v(name)
        assert "secret-ref" in got["signals"], (name, got)
        assert got["primary"] == READ_CREDENTIAL, (name, got)
    # Declaring the thing a secret settles it, whatever the name is: the
    # exception list corrects a guess about a name, and there is no guess here.
    declared = f("jobs:\n  a:\n    steps:\n      - run: echo x\n"
                 "        env:\n          K: ${{ secrets.CACHE_KEY }}\n")
    assert declared["primary"] == READ_CREDENTIAL, declared
    # The remaining limitation, stated as a check so nobody reads the exception
    # list as complete: exact names only.
    assert "secret-ref" in v("NPM_CACHE_KEY")["signals"]


def a_conditional_push_input_is_still_a_push():
    """The `push:` input is the whole of the evidence that
    docker/build-push-action publishes anything, so every value has to be read
    the way the action reads it. Under-reading it leaves a registry write
    sitting inside `self-contained`, and in a corpus that is mostly GitHub
    Actions it does so in bulk. The expression form is what the vendor's own
    starter workflow emits."""
    step = ("on: [pull_request]\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: docker/build-push-action@v5\n")
    with_block = "        with:\n          tags: example/app:ci\n"
    for value in ["true", "'true'", "True", "${{ env.PUBLISH }}",
                  "${{ github.ref_name == github.event.repository.name }}"]:
        got = f(step + with_block + "          push: " + value + "\n")
        assert "build-push-action" in got["signals"], (value, got)
        assert got["primary"] == WRITES_OUTWARD, (value, got)
    for value in ["false", "'false'", "FALSE"]:
        got = f(step + with_block + "          push: " + value + "\n")
        assert "build-push-action" not in got["signals"], (value, got)
        assert got["primary"] == SELF_CONTAINED, (value, got)
    # The input left off is the same build-only case: it is what the action
    # defaults to, and it is why the action alone cannot be the signal.
    assert f(step + with_block)["primary"] == SELF_CONTAINED
    # `push:` is also a trigger name, and a trigger written on one line is not
    # an input. Read as one, every build-only workflow triggered on a push
    # would report as publishing.
    for trig in ["on:\n  push:\n    branches: [main]\n  pull_request:\n",
                 "on:\n  push: {branches: [main]}\n  pull_request:\n",
                 "on:\n  push:\n  pull_request:\n"]:
        got = classify({".github/workflows/w.yml":
                        trig + "jobs:\n  a:\n    steps:\n"
                        "      - uses: docker/build-push-action@v5\n"
                        + with_block})
        assert got[REPO_SCOPE]["primary"] == SELF_CONTAINED, (trig, got)


def github_script_is_a_forge_write_only_where_the_script_calls_the_api():
    """actions/github-script runs JavaScript with an authenticated forge client
    in scope, and plenty of steps use it for `core.*` alone, so the call is the
    evidence and not the action; this signal decides the top class by itself.
    Its error direction is the opposite of most of the table: a body that
    cannot be isolated keeps the signal, because an under-claim here would hide
    a real forge write."""
    step = ("on: [pull_request]\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: actions/github-script@v7\n")

    def script(js):
        return ("        with:\n          script: |\n"
                + "".join("            " + l + "\n" for l in js))
    calls = f(step + script(
        ["github.rest.issues.createComment({issue_number: 1})"]))
    assert "github-script" in calls["signals"], calls
    assert calls["primary"] == ACTS_ON_FORGE, calls
    for js in ["github.graphql(query)", "github.request('GET /x')"]:
        got = f(step + script([js]))
        assert "github-script" in got["signals"], (js, got)
    # The shape the over-claim actually takes: the client is in scope and the
    # script never reaches for it.
    core = f(step + script(["Object.keys(process.env).forEach(k => {",
                            "  core.info(k)",
                            "  core.exportVariable(k, process.env[k])",
                            "})"]))
    assert "github-script" not in core["signals"], core
    assert core["primary"] == SELF_CONTAINED, core
    # A one-line body is read the same way as a block one.
    inline = f(step + "        with:\n          script: core.info(1)\n")
    assert "github-script" not in inline["signals"], inline
    # Where no body can be isolated the signal stays: no `with:` block at all,
    # and a value that only points at a script this does not hold.
    assert "github-script" in f(step)["signals"]
    indirect = f(step + "        with:\n          script: ${{ env.BODY }}\n")
    assert "github-script" in indirect["signals"], indirect
    assert indirect["primary"] == ACTS_ON_FORGE, indirect


def packages_and_id_token_write_are_outward_writes():
    """Two permission grants that are the only evidence of the write they
    allow. `packages: write` is a registry publish; `id-token: write` is the
    keyless path to a registry, a cloud account or a signature, and it is
    invisible to every credential signal precisely because the token it mints
    replaces the credential. Both write outward rather than against the forge
    API, so both rank writes-outward and neither may read as acts-on-forge."""
    def g(perms):
        return f("on: [pull_request]\npermissions:\n  contents: read\n"
                 + perms + "jobs:\n  a:\n    runs-on: ubuntu-latest\n"
                 "    steps:\n      - run: npm ci\n"
                 "      - run: npm run build\n")
    for signal, perm in [("packages-write", "  packages: write\n"),
                         ("id-token-write", "  id-token: write\n")]:
        got = g(perm)
        assert signal in got["signals"], (signal, got)
        assert got["primary"] == WRITES_OUTWARD, (signal, got)
        assert ACTS_ON_FORGE not in got["flags"], (signal, got)
        assert signal in GROUPS[WRITES_OUTWARD], signal
        assert signal not in GROUPS[ACTS_ON_FORGE], signal
        # The quoted spelling some emitters produce says the same thing.
        quoted = g(perm.replace("write", "'write'"))
        assert signal in quoted["signals"], (signal, quoted)
    # A read-only grant of the same key grants nothing, so it raises nothing.
    for perm in ["  packages: read\n", "  id-token: none\n"]:
        assert g(perm)["primary"] == SELF_CONTAINED, perm
    # Why the permission has to be read at all: a keyless publish carries no
    # credential, so nothing else in the file is a signal.
    oidc = g("  id-token: write\n")
    assert "secret-ref" not in oidc["signals"], oidc
    assert "forge-token" not in oidc["signals"], oidc


def the_most_privileged_flag_becomes_the_primary_class():
    """The ladder is only load-bearing where two flags are present at once, so
    that is what is checked. The exclusions are checked with it, because
    read-credential and self-contained are defined by what is *absent* and a
    new signal is exactly what can quietly make one of them co-occur."""
    both = f("jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
             "      - run: docker push registry.example.org/a:1\n"
             "      - uses: actions/github-script@v7\n")
    assert both["primary"] == ACTS_ON_FORGE, both
    assert set(both["flags"]) == {ACTS_ON_FORGE, WRITES_OUTWARD,
                                  rules.CREDENTIALS_UNCLEAR}, both
    # The forge's own token is not a read credential: nobody supplies it.
    tok = f("jobs:\n  a:\n    runs-on: ubuntu-latest\n    env:\n"
            "      T: ${{ secrets.GITHUB_TOKEN }}\n")
    assert tok["primary"] == SELF_CONTAINED, tok
    assert "forge-token" in tok["signals"], tok
    ladder = set(PRECEDENCE)
    for case, files in sorted(fixture_cases().items()):
        prof = classify(files)
        for scope in (PR_SCOPE, REPO_SCOPE):
            p = prof[scope]
            flags = set(p["flags"])
            assert flags <= ladder | set(ASIDE), (case, scope, flags)
            assert p["primary"] == next(x for x in PRECEDENCE
                                        if x in flags), case
            assert len(flags & ladder) >= 1, (case, scope)
            if READ_CREDENTIAL in flags:
                assert not flags & {WRITES_OUTWARD, ACTS_ON_FORGE}, case
            if flags & {SELF_CONTAINED, NO_PULL_REQUEST_TRIGGER, NO_PIPELINE}:
                assert len(flags & ladder) == 1, (case, scope, flags)


def the_forge_token_is_tallied_separately_and_ranks_nothing():
    """The forge-token carve-out is the single judgement that most moves a
    headline distribution, so the flag that exposes it must stay off the ladder
    and must change nobody's class. Buried in the ladder it would be the
    problem it was added to fix: a repository counted acts-on-forge because it
    mentions a token the forge mints for it, with nothing saying so."""
    assert USES_FORGE_TOKEN in ASIDE and USES_FORGE_TOKEN not in PRECEDENCE
    with_write = without_write = 0
    for case, files in sorted(fixture_cases().items()):
        prof = classify(files)
        for scope in (PR_SCOPE, REPO_SCOPE):
            p = prof[scope]
            flags = set(p["flags"])
            assert (USES_FORGE_TOKEN in flags) == ("forge-token"
                                                   in p["signals"]), case
            # Struck out, the ladder answers exactly the same thing. That is
            # what "alters no primary class" means operationally.
            assert p["primary"] == next(
                x for x in PRECEDENCE
                if x in flags - {USES_FORGE_TOKEN}), case
        p = prof[PR_SCOPE]
        if USES_FORGE_TOKEN in p["flags"]:
            if set(p["signals"]) & GROUPS[ACTS_ON_FORGE]:
                with_write += 1
            else:
                without_write += 1
    # Both halves need a fixture, or the number the whole methodology argument
    # rests on is never exercised by anything.
    assert with_write and without_write, (with_write, without_write)


def a_special_runner_ranks_below_every_credential():
    """`special-env` asks for capacity, not trust: a Windows, macOS, GPU or
    self-hosted runner is a bill, and a bill is a smaller decision than a
    permission. Checked on the ladder itself, because the order is the claim.
    """
    assert (PRECEDENCE.index(READ_CREDENTIAL) < PRECEDENCE.index(SPECIAL_ENV)
            < PRECEDENCE.index(SELF_CONTAINED)), PRECEDENCE
    win = f("jobs:\n  a:\n    runs-on: windows-latest\n    steps:\n"
            "      - run: ./build.ps1\n")
    assert win["primary"] == SPECIAL_ENV, win
    mix = f("jobs:\n  a:\n    runs-on: windows-latest\n    env:\n"
            "      T: ${{ secrets.API_TOKEN }}\n")
    assert mix["primary"] == READ_CREDENTIAL, mix
    assert SPECIAL_ENV in mix["flags"], mix


def a_steps_block_at_its_own_column_still_yields_steps():
    """Attribution before anything built on it. A `steps:` whose items are not
    indented past it is legal YAML and was 81 of 505 pull-request-scope files
    in the corpus this was found in; read as an empty block it put the whole
    job's privilege in the frame, where no step could be held responsible for
    it. See EXPERIMENTS.md, "A hand-rolled block parser"."""
    job = ("on:\n  pull_request:\njobs:\n  t:\n    runs-on: ubuntu-latest\n")
    flat = job + "    steps:\n    - run: pytest -q\n    - run: ./report.sh\n"
    deep = job + "    steps:\n      - run: pytest -q\n      - run: ./report.sh\n"
    assert len(actions_steps(flat)[0]) == 2, actions_steps(flat)
    assert len(actions_steps(deep)[0]) == 2, actions_steps(deep)
    # And the sequence is admitted only where a sequence is what the key takes:
    # a `run:` block scalar must still end at a list item in its own column, or
    # one step would swallow the next.
    runs = job + ("    steps:\n    - run: |\n        pytest -q\n"
                  "    - run: ./after.sh\n")
    cmds = [x.strip() for x in actions_commands(runs)]
    assert cmds == ["pytest -q", "./after.sh"], cmds


sys.exit(run([
    ("a release workflow stays out of the pull-request scope",
     release_workflow_stays_out_of_the_pull_request_scope),
    ("a pipeline no pull request triggers is its own state",
     a_pipeline_no_pull_request_triggers_is_its_own_state),
    ("the on: shapes parse, and an unreadable one is in scope",
     the_on_shapes_parse_and_an_unreadable_one_is_in_scope),
    ("pull_request_target is read off the on: declaration only",
     pull_request_target_is_read_off_the_on_declaration_only),
    ("a toolchain assumption is recorded and ranks nothing",
     a_toolchain_assumption_is_recorded_and_ranks_nothing),
    ("an ordinary _KEY variable is not read as a credential",
     an_ordinary_key_variable_is_not_read_as_a_credential),
    ("a conditional push: input is still a push",
     a_conditional_push_input_is_still_a_push),
    ("github-script is a forge write only where the script calls the API",
     github_script_is_a_forge_write_only_where_the_script_calls_the_api),
    ("packages: write and id-token: write are outward writes",
     packages_and_id_token_write_are_outward_writes),
    ("the most privileged flag becomes the primary class",
     the_most_privileged_flag_becomes_the_primary_class),
    ("the forge token is tallied separately and ranks nothing",
     the_forge_token_is_tallied_separately_and_ranks_nothing),
    ("a special runner ranks below every credential",
     a_special_runner_ranks_below_every_credential),
    ("a steps: block at its own column still yields steps",
     a_steps_block_at_its_own_column_still_yields_steps),
]))
