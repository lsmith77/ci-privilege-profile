#!/usr/bin/env python3
"""The outputs: the profile JSON, and the summary a reader reviews.

Two audiences, the same figures. The JSON is what somebody finds months later
and re-derives a number from; the printed summary is what a person reads after
a run and reviews a rule change against. Anything that qualifies a figure has
to be in both, because the terminal scrolls away and the file outlives it.

THE OUTPUT FILES, AND WHY THEY REFUSE TO OVERWRITE EACH OTHER BY NAME
---------------------------------------------------------------------
    ci_profile.json              a sweep's own profile
    ci_profile_from_cache.json   a cached re-analysis's, never the above
    ci_cache.json                the evidence, never a profile
    fork_pr_profile.json         the fork observation

A sweep of a sizeable corpus costs hours, so a mode that overwrote another
mode's output would destroy a run in progress with no error anywhere. Each
writer therefore refuses the names that belong to the others, BY BASENAME, and
that detail is the point. A test that proved the guard by aiming a real write at
the real profile destroyed that file the moment the guard was mutated away.
Matching on the basename lets every test write at a scratch directory and still
prove the property. See EXPERIMENTS.md, "A destructive test".
"""
import json
import os
import sys
from datetime import date

from .cache import banner
from .classify import (ASIDE, NO_PIPELINE, NO_PULL_REQUEST_TRIGGER,
                       PRECEDENCE, PR_SCOPE, REPO_SCOPE, contributor_runnable,
                       forge_token_split, primary_of, tests_unprivileged)
from .structure import parser_available

PROFILE_NAME = "ci_profile.json"
FROM_CACHE_NAME = "ci_profile_from_cache.json"
CACHE_NAME = "ci_cache.json"
FORK_NAME = "fork_pr_profile.json"
ALL_OUTPUT_NAMES = frozenset(
    [PROFILE_NAME, FROM_CACHE_NAME, CACHE_NAME, FORK_NAME])


def refuse_overwrite(path, own):
    """Exit if `path`'s basename belongs to one of the other outputs.

    `own` is the name this writer is allowed to produce. Everything else in
    ALL_OUTPUT_NAMES is somebody else's hours of fetching.
    """
    base = os.path.basename(path)
    if base in ALL_OUTPUT_NAMES - {own}:
        sys.exit("refusing to write {}: that name belongs to another output "
                 "of this tool, and overwriting it would destroy a "
                 "measurement".format(base))


COMMENT = (
    "What privilege each repository's CI pipeline would need in order to run, "
    "and whether a contributor on their own infrastructure could run it. "
    "Read-only; every figure here is signal detection over pipeline text, not "
    "execution. "
    "Each repository carries two profiles. `pull_request` covers only the "
    "workflows a contributor's own pull request triggers, and is the figure to "
    "quote: it answers what a contributor must be able to run. `repository` "
    "covers every pipeline file, which is what the project needs overall: a "
    "maintainer's release workflow is a real requirement, just not one a "
    "contributor meets. Within each, `primary` is the most privileged flag "
    "present; the ladder is acts-on-forge > writes-outward > read-credential > "
    "special-env > self-contained > no-pull-request-trigger > no-pipeline, and "
    "thin-wrapper, uses-pull-request-target, uses-forge-token, "
    "assumes-toolchain, the credentials-* axis and the test-step-* "
    "determination are reported alongside it rather than on it. "
    "no-pull-request-trigger is a repository with pipelines that no pull "
    "request sets off, kept apart from no-pipeline, which has none at all. "
    "assumes-toolchain is an environment dependency and not a privilege "
    "class: `self-contained` means no secret, no outward write and no special "
    "runner label, never 'would run on a bare container', and the toolchain-* "
    "signals are what a shared runner image would have to carry. "
    "`forge_token` splits uses-forge-token into the repositories that also "
    "carry a forge-write signal, so they are acts-on-forge on their own "
    "evidence, and those that carry none, whose class rests entirely on the "
    "judgement that the forge's own auto-minted token is not a credential a "
    "contributor has to supply. That second figure is the size of the "
    "disagreement, so the headline can be restated under a stricter reading "
    "without re-running the sweep. "
    "The credentials-* flag says what the privilege is FOR rather than how "
    "large it is: credentials-reporting-only where every privileged step in "
    "the scope records a result (a coverage upload, a test-result publisher, a "
    "sticky pull-request comment, a chat notification) and a contributor could "
    "therefore run the tests by skipping those steps; credentials-test-time "
    "where a credential is what dependency resolution needs, so nothing runs "
    "without it; credentials-unclear where one privileged step was recognised "
    "as neither, which a SINGLE unrecognised step is enough to cause, since "
    "reporting-only is a claim about every privileged step in the scope and is "
    "never reached by default. Absent means the scope needs no privilege at "
    "all. `contributor_runnable` derives the figure the axis exists for, per "
    "scope: the self-contained repositories plus those whose privilege is "
    "entirely reporting, with the unclear count as the uncertainty band around "
    "it. That band is wide, and EXPERIMENTS.md records why it did not narrow. "
    "The test-step-* determination asks a narrower question than the "
    "credentials-* axis: not whether every privileged step in the scope is "
    "droppable, but whether the step that invokes the test suite consumes a "
    "credential, which is what a contributor wanting a pre-flight signal needs "
    "to know. test-step-unprivileged where an identified test invocation has "
    "no credential available to it, counting a credential reachable by "
    "inheritance from a workflow-level or job-level `env:` (or GitLab's global "
    "or job `variables:`) as available, and counting the forge's own "
    "auto-minted token as no credential, consistently with uses-forge-token; "
    "test-step-privileged where one is available, which includes the case "
    "where whether one is reachable could not be determined, since the "
    "flattering answer must not win by default; test-step-unidentified where "
    "no command form the tool recognises as a test invocation was found, which "
    "is a statement about what the configuration says and not about the "
    "project. `tests_unprivileged` derives the figure that determination "
    "exists for, per scope, with test-step-unidentified as its band. "
    "A signal can be missed or over-claimed, so `signals` carries the "
    "evidence. Repositories under `unknown` could not be read and are excluded "
    "from every count, never counted as no-pipeline. `other_ci` names CI "
    "definitions at the root that this tool does not read (Travis, Jenkins, "
    "Drone and the like), so no-pipeline is not read as 'no CI'.")


def write(path, repos, unknown, source=None, partial=False, limited=False,
          cache=None, extra=None):
    """The profile JSON. Returns the path written."""
    own = FROM_CACHE_NAME if cache is not None else PROFILE_NAME
    refuse_overwrite(path, own)
    referencing, with_write, without_write = forge_token_split(repos)
    out = {
        "$comment": COMMENT
        + (" PARTIAL: interrupted mid-sweep." if partial else "")
        + (" PARTIAL: a limit was in force, so this covers a prefix of the "
           "corpus and not a sample of it." if limited else ""),
        "scanned": date.today().isoformat(),
        "partial": bool(partial or limited),
        "structural_parser": parser_available(),
        "source": source.describe() if source is not None else None,
        "forge_token": {
            "repos": referencing,
            "with_forge_write": with_write,
            "without_forge_write": without_write,
        },
        "contributor_runnable": {
            scope: dict(zip(("repos", "self_contained", "reporting_only",
                             "unclear"),
                            contributor_runnable(repos, scope)))
            for scope in (PR_SCOPE, REPO_SCOPE)
        },
        "tests_unprivileged": {
            scope: dict(zip(("repos", "privileged", "unidentified"),
                            tests_unprivileged(repos, scope)))
            for scope in (PR_SCOPE, REPO_SCOPE)
        },
        "repos": dict(sorted(repos.items(), key=lambda kv: kv[0].lower())),
        "unknown": dict(sorted(unknown.items(), key=lambda kv: kv[0].lower())),
    }
    for key, value in (extra or {}).items():
        out[key] = value
    if cache is not None:
        # The banner goes first, in the key a reader's eye lands on, and the
        # dates go with it. `scanned` is therefore the oldest fetch date rather
        # than today, because it has always meant when the corpus was read,
        # and `reanalysed` is when these rules ran over it.
        out["$comment"] = banner(cache) + " " + out["$comment"]
        out["from_cache"] = True
        out["scanned"] = cache["fetched_oldest"]
        out["reanalysed"] = date.today().isoformat()
        out["cache_fetched"] = [cache["fetched_oldest"],
                                cache["fetched_newest"]]
        out["cache_partial"] = cache.get("partial", False)
        out["partial"] = bool(out["partial"] or cache.get("partial"))
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    return path


def report_scope(repos, unknown, scope, width, log=print):
    """One scope's distribution table, with the flags reported beside it."""
    counts = {c: 0 for c in PRECEDENCE}
    foreign = 0
    for prof in repos.values():
        primary = prof[scope]["primary"]
        counts[primary] = counts.get(primary, 0) + 1
        if primary == NO_PIPELINE and prof.get("other_ci"):
            foreign += 1
    # NO_PULL_REQUEST_TRIGGER cannot arise outside the pull-request scope: a
    # scope holding pipeline files always lands on a real class. Printing it as
    # a permanent zero would invite the reader to wonder what it meant there.
    for cls in PRECEDENCE:
        if cls == NO_PULL_REQUEST_TRIGGER and scope != PR_SCOPE:
            continue
        extra = ""
        if cls == NO_PIPELINE and foreign:
            extra = ("   ({} with a CI definition this tool does not read)"
                     .format(foreign))
        if cls == NO_PULL_REQUEST_TRIGGER:
            extra = "   (a pipeline, but nothing a pull request triggers)"
        log("  {:<{w}}  {:>5}{}".format(cls, counts[cls], extra, w=width))
    log("  {:<{w}}  {:>5}   (excluded from the distribution)".format(
        "unknown", len(unknown), w=width))
    log("  reported alongside the classes above, not part of them:")
    for flag in ASIDE:
        n = sum(1 for p in repos.values() if flag in p[scope]["flags"])
        log("    {:<{w}}  {:>5}".format(flag, n, w=width))
    # The figure the axis exists for, printed beside the distribution it is
    # derived from and never on its own: the uncertainty band belongs to the
    # answer, and a single number here would be read as a measurement.
    total, plain, reporting, unclear = contributor_runnable(repos, scope)
    log("  {:<{w}}  {:>5}".format(
        "contributor-runnable if reporting steps are dropped", total, w=width))
    log("    = {} self-contained + {} whose every privileged step is "
        "reporting".format(plain, reporting))
    log("    ± {} credentials-unclear, the uncertainty band: one privileged "
        "step each".format(unclear))
    log("      that was recognised as neither, which is what holds them out "
        "of the figure")
    # The narrower figure, printed the same way and for the same reason: the
    # count of scopes whose test invocation nothing could find belongs to the
    # answer, because a test suite that could not be found is not one that
    # needs nothing.
    clean, privileged, unidentified = tests_unprivileged(repos, scope)
    log("  {:<{w}}  {:>5}".format(
        "with a test suite that runs unprivileged", clean, w=width))
    log("    vs {} whose test step has a credential available to it, "
        "inherited".format(privileged))
    log("       environment included, and {} where no test invocation could be"
        .format(unidentified))
    log("       identified, which is this figure's band")


def report(before, repos, unknown, cache=None, source=None, log=print):
    """The review gate. A rule change is reviewed against what this prints."""
    width = max(len(c) for c in PRECEDENCE + ASIDE)
    if cache:
        log(banner(cache))
    if not parser_available():
        log("NOTE: no YAML parser available, so the structural reading fell "
            "back to\nindentation. The two agree on every fixture; where they "
            "can differ is the\nlong tail of shapes a line reader cannot "
            "see. Install PyYAML for the\nparser-backed reading.")
    log("\nclassified {} repositories, in two scopes.".format(len(repos)))
    log("\nPULL-REQUEST SCOPE: THE FIGURE TO QUOTE. Only the workflows a")
    log("contributor's own pull request triggers, which is the question:")
    log("what a contributor must be able to run.")
    report_scope(repos, unknown, PR_SCOPE, width, log)
    # The forge-token carve-out, as a number a reader can re-derive the
    # headline from. Over the quoted scope, for the same reason.
    referencing, with_write, without_write = forge_token_split(repos, PR_SCOPE)
    log("  of the {} referencing the forge's own token:".format(referencing))
    log("    {:>5} also carry a forge-write signal, so they are acts-on-forge"
        .format(with_write))
    log("    {:>5} carry no forge-write signal: the size of the "
        "disagreement, and".format(without_write))
    log("          what a stricter reading would count as needing a "
        "credential")
    log("\nWHOLE REPOSITORY: every pipeline file, release and deploy")
    log("workflows included. What the project needs overall, and")
    log("NOT the figure to quote for what a contributor must be able to run:")
    report_scope(repos, unknown, REPO_SCOPE, width, log)
    log("\nIn neither scope does `self-contained` mean the job would start on")
    log("a bare container: it means no secret, no outward write and no")
    log("special runner label. What the runner must already carry is a")
    log("separate question: the assumes-toolchain tally above and the")
    log("toolchain-* signals behind it.")
    log("\nNor is `self-contained` the figure the contributor question turns")
    log("on. It says whose pipeline needs nothing granted as written; the")
    log("question is whose tests a contributor could run on their own")
    log("infrastructure, and a pipeline whose only privileged step uploads")
    log("coverage answers yes to that while failing `self-contained`. The")
    log("contributor-runnable line in each table above is that figure, and")
    log("its uncertainty band is wide; see EXPERIMENTS.md.")

    if not before:
        log("\nno previous profile to compare against")
    else:
        changed = []
        for key, prof in sorted(repos.items()):
            if key not in before:
                continue
            was = (primary_of(before[key], PR_SCOPE),
                   primary_of(before[key], REPO_SCOPE))
            now = (prof[PR_SCOPE]["primary"], prof[REPO_SCOPE]["primary"])
            if was != now:
                changed.append((key, was, now))
        added = sorted(k for k in repos if k not in before)
        dropped = sorted(k for k in before if k not in repos)
        if not (changed or added or dropped):
            log("\nno change since the previous profile")
        else:
            for key, was, now in changed:
                log("  CHANGED {}: pull-request {} -> {}, whole-repository "
                    "{} -> {}".format(key, was[0], now[0], was[1], now[1]))
            for key in added:
                log("  NEW     {}: {} in the pull-request scope, {} overall"
                    .format(key, repos[key][PR_SCOPE]["primary"],
                            repos[key][REPO_SCOPE]["primary"]))
            for key in dropped:
                log("  DROPPED {} (was {})".format(key,
                                                   primary_of(before[key])))

    if unknown:
        log("\n{} recorded as unknown (could not be read, so excluded from "
            "every count above):".format(len(unknown)))
        for key in sorted(unknown)[:20]:
            log("  {}: {}".format(key, unknown[key]))
        if len(unknown) > 20:
            log("  ... and {} more".format(len(unknown) - 20))
    if source is not None:
        for line in source.limitations:
            log("\nLIMITATION: " + line)
    # Repeated below the figures as well as above them: the terminal scrolls,
    # and a reader who arrives at the distribution from either direction has to
    # meet the date before the numbers.
    if cache:
        log("\n" + banner(cache))


def previous_profile(path):
    """A previous profile's repos map, read only to diff against.

    Never fatal: the point of a re-run is the rule change it shows, and a
    profile that cannot be parsed is a reason to show the distribution without
    a comparison rather than to refuse to show it.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            return json.load(fh).get("repos") or {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


__all__ = ["ALL_OUTPUT_NAMES", "CACHE_NAME", "COMMENT", "FORK_NAME",
           "FROM_CACHE_NAME", "PROFILE_NAME", "previous_profile",
           "refuse_overwrite", "report", "report_scope", "write"]
