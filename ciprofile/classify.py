#!/usr/bin/env python3
"""Two profiles per repository, and which of them answers the question.

TWO SCOPES, AND WHICH ONE TO QUOTE
----------------------------------
Every repository is profiled twice, because "what CI does this project need"
and "what must a contributor be able to run" are different questions with
different answers.

  - `pull_request`: the workflows a contributor's own pull request triggers,
    and nothing else. THIS IS THE FIGURE TO QUOTE. A contributor opening a
    pull request runs the pull-request-triggered workflows and never the
    release or deploy ones, so the privilege those others need is not a
    privilege the contributor's infrastructure has to grant.
  - `repository`: every pipeline file. This describes what the project needs
    overall: the maintainer's release workflow is a real requirement on
    whatever runs the release, just not one a contributor meets.

Unioning the signals across every file instead is wrong in bulk rather than at
the margin, which is a measured result and not a worry: a repository whose
pull-request check was pure lint classified as `writes-outward` because an
unrelated release workflow ran `npm publish`. Nearly every mature project
carries such a workflow. See EXPERIMENTS.md, "Whole-repository versus
trigger-scoped classification".

`thin-wrapper` is computed per scope for the same reason: it dies on the first
non-thin command, so an unscoped reading lets a release workflow's shell
plumbing destroy the reading of a one-line pull-request check.

What lands in the pull-request scope: a workflow whose `on:` declares
`pull_request` or `pull_request_target`; a reusable workflow
(`workflow_call`), whose callers are not readable from the file, so it is kept
visible rather than assumed to be release-only; a workflow whose `on:` cannot
be read at all; and a GitLab `.gitlab-ci.yml`, in full. The error direction is
deliberate: an undeterminable trigger counts as in scope, so a privileged
workflow stays visible in the quoted figure instead of being hidden from it.

The one caveat on the pull-request scope worth stating outright: a contributor
pushing a branch to their own fork runs that fork's `push`-triggered workflows
too, and those are out of this scope. A project whose checks hang off `push`
rather than `pull_request` therefore reads lighter here than a contributor's
infrastructure would actually need, and the repository scope is the nearer
answer for it. `merge_group` is out for the same kind of reason and a weaker
one, since a merge queue runs on the maintainer's side. Neither is folded in,
because `pull_request` is the trigger that is unambiguously the contributor's
own and a scope that admits `push` admits most release workflows with it.

A repository that has a pipeline but nothing a pull request triggers is its own
state in the pull-request scope, `no-pull-request-trigger`, counted separately
from `no-pipeline`. The two say different things (one project does no CI, the
other does CI a contributor never sets off), and folding them together would
inflate `no-pipeline`, which is among the figures most likely to be quoted.

`self-contained` IS NOT "RUNS ON A BARE RUNNER"
-----------------------------------------------
`self-contained` means the pipeline needs no secret, writes nowhere and asks
for no special runner label. It does NOT mean the job would start on an empty
container. A hosted runner image ships with node, python, java, go, docker and
much else already installed, so `npm test` on `ubuntu-latest` is
`self-contained` and still assumes a toolchain somebody has to have put there.

So what a shared standard runner image would have to carry is a separate
question from what privilege a host has to grant, and `assumes-toolchain`
answers it separately: the `actions/setup-*` family a workflow calls and the
container images its jobs name, recorded as `toolchain-*` signals. It is
deliberately off the precedence ladder and changes no primary class: an
environment dependency is a bill, not a trust decision. Do not quote
`self-contained` as "runs on a bare runner"; it is not that number, and the
`toolchain-*` signals are what a reader needs instead.
"""
from . import rules
from .rules import (ACTS_ON_FORGE, ASIDE, ASSUMES_TOOLCHAIN,
                    CREDENTIALS_REPORTING_ONLY, CREDENTIALS_TEST_TIME,
                    CREDENTIALS_UNCLEAR, GROUPS, NO_PIPELINE,
                    NO_PULL_REQUEST_TRIGGER, PRECEDENCE, PULL_REQUEST_TARGET,
                    READ_CREDENTIAL, SELF_CONTAINED, SPECIAL_ENV,
                    TEST_STEP_PRIVILEGED, TEST_STEP_UNIDENTIFIED,
                    TEST_STEP_UNPRIVILEGED, THIN_WRAPPER, TOOLCHAIN_PREFIX,
                    USES_FORGE_TOKEN, WRITES_OUTWARD)
from .structure import commands, in_pull_request_scope

# The two profiles every repository carries. PR_SCOPE is the one to quote.
PR_SCOPE = "pull_request"
REPO_SCOPE = "repository"
SCOPES = (PR_SCOPE, REPO_SCOPE)


def _scope_profile(per_file, paths, absent):
    """One scope's {primary, flags, signals, files}.

    `absent` is the class an empty scope records: NO_PIPELINE where the
    repository holds no pipeline file at all, NO_PULL_REQUEST_TRIGGER where it
    holds pipelines that no pull request sets off.
    """
    signals, cmds = set(), []
    for path in paths:
        file_sig, file_cmds = per_file[path]
        signals |= file_sig
        cmds += file_cmds

    flags = []
    if not paths:
        flags.append(absent)
    else:
        forge = signals & GROUPS[ACTS_ON_FORGE]
        outward = signals & GROUPS[WRITES_OUTWARD]
        env = signals & GROUPS[SPECIAL_ENV]
        secret = "secret-ref" in signals
        if forge:
            flags.append(ACTS_ON_FORGE)
        if outward:
            flags.append(WRITES_OUTWARD)
        # By definition: a secret that is only ever read. An outward or forge
        # write is what the secret is *for* once either is present, so the two
        # are not stacked.
        if secret and not outward and not forge:
            flags.append(READ_CREDENTIAL)
        if env:
            flags.append(SPECIAL_ENV)
        if not (forge or outward or secret or env):
            flags.append(SELF_CONTAINED)
        # A pipeline with no run steps at all (every step a `uses:`) is not a
        # wrapper around anything, so it does not qualify.
        if cmds and all(rules.is_thin(c) for c in cmds):
            flags.append(THIN_WRAPPER)
        if "pull-request-target" in signals:
            flags.append(PULL_REQUEST_TARGET)
        if "forge-token" in signals:
            flags.append(USES_FORGE_TOKEN)
        if any(s.startswith(TOOLCHAIN_PREFIX) for s in signals):
            flags.append(ASSUMES_TOOLCHAIN)
        # What the privilege is for, across every file in the scope at once:
        # one file's reporting step does not make the scope reporting-only if
        # another file holds a privilege nothing recognised.
        purpose = rules.credentials_purpose(signals)
        if purpose:
            flags.append(purpose)
        # And the narrower question, over the same union: whether the step that
        # invokes the test suite consumes a credential. Always one of three
        # values where the scope holds a pipeline file, because "no test
        # invocation could be identified" is one of them; absent only for the
        # two empty scopes, where there is no step to ask about.
        flags.append(rules.test_step_privilege(signals))

    order = PRECEDENCE + ASIDE
    flags.sort(key=order.index)
    return {
        "primary": next(f for f in PRECEDENCE if f in flags),
        "flags": flags,
        "signals": sorted(signals),
        "files": sorted(paths),
    }


def classify(files, other_ci=()):
    """One repository's two profiles from {path: text}.

    `files` holds only the pipeline definitions; an empty mapping is the
    no-pipeline case. A repository that could not be read never reaches here;
    see the unknown handling in sweep.py.

    Both scopes are returned, `pull_request` first because it is the figure to
    quote. Each file's signals and commands are read once and unioned per
    scope, so a file in both costs nothing extra.
    """
    per_file, scoped = {}, []
    for path, raw in sorted(files.items()):
        per_file[path] = (rules.file_signals(path, raw), commands(path, raw))
        if in_pull_request_scope(path, raw):
            scoped.append(path)

    out = {
        PR_SCOPE: _scope_profile(
            per_file, scoped,
            NO_PULL_REQUEST_TRIGGER if files else NO_PIPELINE),
        REPO_SCOPE: _scope_profile(per_file, sorted(files), NO_PIPELINE),
    }
    if other_ci:
        out["other_ci"] = sorted(other_ci)
    return out


def forge_token_split(repos, scope=PR_SCOPE):
    """(referencing, with_forge_write, without_forge_write).

    The forge-token carve-out's own numbers, over classified profiles.
    `without` is the population whose class rests entirely on the judgement
    that the forge's own token is not a credential a contributor supplies. It
    is the figure to quote when that judgement is challenged, because it is
    the size of the disagreement and nothing has to be re-run to restate the
    headline under the stricter reading.

    Over the pull-request scope by default, since that is the scope the
    headline is quoted from.
    """
    referencing = with_write = 0
    for prof in repos.values():
        sub = prof[scope]
        if USES_FORGE_TOKEN not in sub["flags"]:
            continue
        referencing += 1
        if set(sub["signals"]) & GROUPS[ACTS_ON_FORGE]:
            with_write += 1
    return referencing, with_write, referencing - with_write


def contributor_runnable(repos, scope=PR_SCOPE):
    """(total, self_contained, reporting_only, unclear).

    Contributor-runnable if reporting steps are dropped: the scope's
    `self-contained` repositories, which need nothing granted as written, plus
    those whose every privileged step is reporting, which need nothing granted
    once those steps are skipped. `unclear` rides along because the uncertainty
    band is part of the answer, and in the corpora this has been run against it
    is the largest of the three numbers. EXPERIMENTS.md records why, and why
    the band did not narrow.

    The two populations cannot overlap (`self-contained` is defined by the
    absence of the privilege the axis is about), so the total is a sum and not
    a union.

    One asymmetry, in the under-claiming direction as everywhere else: the base
    is `self-contained`, which needs no special runner either, so a
    `special-env` scope that needs no privilege at all is not in the base while
    one whose only privilege is reporting is. Like `self-contained`, the figure
    speaks about privilege and says nothing about capacity.
    """
    plain = reporting = unclear = 0
    for prof in repos.values():
        sub = prof[scope]
        flags = set(sub["flags"])
        if sub["primary"] == SELF_CONTAINED:
            plain += 1
        elif CREDENTIALS_REPORTING_ONLY in flags:
            reporting += 1
        if CREDENTIALS_UNCLEAR in flags:
            unclear += 1
    return plain + reporting, plain, reporting, unclear


def tests_unprivileged(repos, scope=PR_SCOPE):
    """(unprivileged, privileged, unidentified).

    The figure the test-step determination exists for, beside the
    contributor-runnable one above and answering a narrower question: how many
    repositories have a test suite that runs without the project's secrets,
    whatever the steps around it need. Where contributor_runnable() needs every
    privileged step in a scope to be recognised as reporting, this needs only
    the test step to be clean, so it is reachable in cases that axis leaves
    unclear.

    All three are returned and the three sum to the scopes holding a pipeline
    file, because `unidentified` is the band around the first figure in exactly
    the way `unclear` is the band around contributor_runnable()'s: a test suite
    this could not find is not a test suite that needs nothing.
    """
    counts = {TEST_STEP_UNPRIVILEGED: 0, TEST_STEP_PRIVILEGED: 0,
              TEST_STEP_UNIDENTIFIED: 0}
    for prof in repos.values():
        for flag in prof[scope]["flags"]:
            if flag in counts:
                counts[flag] += 1
    return (counts[TEST_STEP_UNPRIVILEGED], counts[TEST_STEP_PRIVILEGED],
            counts[TEST_STEP_UNIDENTIFIED])


def primary_of(prof, scope=PR_SCOPE):
    """One scope's primary class, or None where the profile has no such scope.

    Defensive because a previous profile is an input a run only reads: an entry
    whose class cannot be read out of it must not abort a sweep.
    """
    return (prof.get(scope) or {}).get("primary")


__all__ = ["PR_SCOPE", "REPO_SCOPE", "SCOPES", "classify",
           "contributor_runnable", "forge_token_split", "primary_of",
           "tests_unprivileged",
           "ACTS_ON_FORGE", "WRITES_OUTWARD", "READ_CREDENTIAL",
           "SPECIAL_ENV", "SELF_CONTAINED", "NO_PULL_REQUEST_TRIGGER",
           "NO_PIPELINE", "THIN_WRAPPER", "PULL_REQUEST_TARGET",
           "USES_FORGE_TOKEN", "ASSUMES_TOOLCHAIN",
           "CREDENTIALS_REPORTING_ONLY", "CREDENTIALS_TEST_TIME",
           "CREDENTIALS_UNCLEAR", "TEST_STEP_UNPRIVILEGED",
           "TEST_STEP_PRIVILEGED", "TEST_STEP_UNIDENTIFIED",
           "PRECEDENCE", "ASIDE", "GROUPS"]
