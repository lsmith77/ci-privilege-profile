#!/usr/bin/env python3
"""Running the pipeline with nothing granted, and watching what happens.

Everything else in this tool reads pipeline text. This runs it. One repository
at a time, in a container, with **no secret of any kind supplied**, and records
what the run did.

WHY EXECUTION ANSWERS WHAT READING CANNOT
-----------------------------------------
The static side leaves a wide band undecided, and the band has one cause: the
information is not in the file. Of the 361 repositories with a
pull-request-triggered pipeline in the corpus this was developed against, 155
carry a credential whose purpose is written down nowhere, and 220 yield no
command form recognisable as a test invocation. Both are failures to *find*
something. Execution does not have to find it: it runs the pipeline and
observes, so a test suite behind `./gradlew build`, a project shell script, a
`make` target or a devenv wrapper is reached without any rule knowing it is
there.

THE MEASURED OUTCOME IS NOT A GREEN RUN
---------------------------------------
A green workflow is the wrong bar and would make this instrument useless. Most
pipelines fail under a local runner for reasons that have nothing to do with
privilege: an action the local runner cannot resolve, a service container, a
missing system package, a registry that was slow, an architecture mismatch. If
"green" were the signal, the result would be a measurement of the runner.

The question is narrower: **did the pull-request check execute, with no secret
present, without failing for a secret-related reason?** If the project's own
commands ran at all while nothing was granted, then nothing granted was
blocking them, whatever became of the rest of the run. That is the whole claim,
and it is the claim a contributor wanting a pre-flight signal is asking about.

THE SIX OUTCOMES, AND WHICH OF THEM PROVE ANYTHING
--------------------------------------------------
    ran-unprivileged      every step ran and the job exited zero, with no
                          secret supplied. EVIDENCE: nothing granted was
                          needed. Not a heuristic: no secret existed to be
                          consumed.
    ran-with-failures     a project command executed and failed on its own
                          merits (findings from a linter, a failing assertion,
                          a compile error). EVIDENCE: still an answer, because
                          the pipeline got far enough to run the project's own
                          code without a credential.
    secret-required       a step failed and its own output names a missing or
                          empty secret, or an authentication rejection.
                          EVIDENCE: it needs one.
    environment-failure   it failed before the project's commands, for a
                          reason belonging to the runner and not the pipeline.
                          PROVES NOTHING.
    timed-out            the per-repository budget ran out. PROVES NOTHING.
    not-attempted        the clone failed, or the runner found no job to run.
                          PROVES NOTHING.

**The positive case is not heuristic and the failure cases are.**
`ran-unprivileged` rests on an absence that is enforced by construction rather
than detected: no secret file is read, no secret is passed, and the credential
shaped variables are taken out of the runner's own environment. Nothing can
have consumed a secret because there was none. Every other class is a reading
of log text, and the reading is wrong in a knowable direction:

**ambiguity resolves to `environment-failure`, which proves nothing.** A
failure is never read as `secret-required` unless the failing step's own output
says so, and never as `ran-with-failures` unless a positive merit pattern
matched. Anything the patterns do not recognise falls through to the class that
supports no claim in either direction. So this under-claims on both sides,
which is the same asymmetry the credentials axis and the test-step
determination hold to.

WHAT A CLEAN RUN IS EVIDENCE *ABOUT*
------------------------------------
The scope is the pull-request check, not the test suite. A workflow with no
recognised test invocation that runs clean proves that the check a contributor
triggers needs nothing granted; it does not prove a test suite exists behind it.
Both readings are wanted, so `test_invocation_recognised` is recorded per
repository from the static rules, and a run over a scope where it is false says
something about the check and nothing about the tests. Do not collapse the two.

THIS EXECUTES THIRD-PARTY CODE
------------------------------
A pipeline is a script somebody else wrote for infrastructure they chose, and
this runs it on the operator's machine. It is confined to a container, the
container is given no secret and no access to the host's container daemon, and
the clone is removed afterwards; none of that makes it safe to point at an
arbitrary corpus. The consent question is real and is the reason the sample
size has no default: see USAGE.md and EXPERIMENTS.md.

WHAT THE RUNNER IS, AND WHAT THAT COSTS
---------------------------------------
`act` runs GitHub Actions workflows locally. It reads no other grammar, so a
GitLab, Woodpecker or Jenkins pipeline cannot be sampled here at all, and that
is a selection constraint rather than a limitation of the method. It is also
handed one event, `pull_request`, so a scope holding nothing that event can
start is excluded at selection rather than cloned and run: see
unrunnable_scope(). On an ARM host the runner images are amd64 and run under
emulation, which is slow enough to dominate the per-file cost and to make
TIMEOUT_DEFAULT a real constraint rather than a safety net.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ciprofile.classify import PR_SCOPE, REPO_SCOPE                # noqa: E402
from ciprofile.report import DIFFERENTIAL_NAME, refuse_overwrite   # noqa: E402
from ciprofile.rules import (CREDENTIALS_UNCLEAR, NO_PIPELINE,     # noqa: E402
                             NO_PULL_REQUEST_TRIGGER, SPECIAL_ENV,
                             TEST_INVOCATION, TEST_STEP_UNIDENTIFIED,
                             TOOLCHAIN_PREFIX)
# The same set the GitHub adapter keeps out of the denominator, imported
# rather than restated: two copies of this list is how the selection comes to
# execute a repository the corpus does not even count.
from ciprofile.sources.github import PROFILE_REPO_NAMES           # noqa: E402
from ciprofile.structure import (actions_triggers,                # noqa: E402
                                 strip_comments)

# ------------------------------------------------------------ the outcomes

RAN_UNPRIVILEGED = "ran-unprivileged"
RAN_WITH_FAILURES = "ran-with-failures"
SECRET_REQUIRED = "secret-required"
ENVIRONMENT_FAILURE = "environment-failure"
TIMED_OUT = "timed-out"
NOT_ATTEMPTED = "not-attempted"

# The three that answer the question, in either direction, and the three that
# do not. Every share this reports is over the first set, with the second
# stated beside it, for the same reason an unreadable repository is excluded
# from the static distributions rather than counted as `no-pipeline`.
ANSWERS = (RAN_UNPRIVILEGED, RAN_WITH_FAILURES, SECRET_REQUIRED)
PROVES_NOTHING = (ENVIRONMENT_FAILURE, TIMED_OUT, NOT_ATTEMPTED)
OUTCOMES = ANSWERS + PROVES_NOTHING

# Aggregating a repository's workflow files. Strict rather than generous: one
# file nothing could be concluded about holds the whole repository
# unanswered, because the question is what a contributor has to be able to run
# and that is every check their pull request sets off, not the cheapest one.
# A secret-related failure outranks everything, so a privilege stays visible.
AGGREGATE_PRECEDENCE = (SECRET_REQUIRED, NOT_ATTEMPTED, TIMED_OUT,
                        ENVIRONMENT_FAILURE, RAN_WITH_FAILURES,
                        RAN_UNPRIVILEGED)

# ------------------------------------------------------------ the log patterns
#
# Each table says what it is evidence of and which way it is wrong. The order
# the tables are consulted in is itself load-bearing and is in
# classify_outcome().

# The runner's own inability, consulted FIRST. It has to come before the
# credential table because the two overlap: `act` fetches actions from a public
# API unauthenticated, so a rate-limit rejection reads exactly like a project's
# own missing token if the credential table is asked first. Wrong direction:
# toward `environment-failure`, which claims nothing.
RUNNER_LIMIT = re.compile(
    r"unable to resolve action"
    r"|failed to (?:pull|load) image"
    r"|no matching manifest for linux/"
    r"|exec format error"
    r"|OCI runtime (?:create|exec) failed"
    r"|error response from daemon"
    r"|cannot connect to the docker daemon"
    r"|docker: (?:command not found|not found)"
    r"|api rate limit exceeded|rate limit exceeded"
    r"|unsupported (?:platform|architecture)"
    r"|the `[\w-]+` (?:feature|input) is not supported"
    r"|services are not supported"
    r"|container [\w./-]+ is not running"
    r"|no space left on device"
    r"|unable to (?:reserve|get) cache"
    r"|cache service responded with",
    re.I)

# A credential was missing, empty, or rejected. Matched ONLY against the
# failing step's own output, never the whole log: a warning from an earlier
# step would otherwise hand out this reading for free, and this is the one
# reading that must not be given away. Wrong direction: this list is
# incomplete, so a project that does need a secret and said so in wording
# nothing here matches falls to `environment-failure` and claims nothing.
# It never produces a false `ran-unprivileged`, because that class requires an
# exit code of zero and no failing step at all.
CREDENTIAL_FAILURE = re.compile(
    r"input required and not supplied"
    r"|401 unauthorized|403 forbidden|\b407 proxy authentication"
    r"|\bunauthorized\b|\bforbidden\b"
    r"|authentication (?:required|failed)|authentication is required"
    r"|bad credentials|invalid credentials|credentials (?:could not|not) "
    r"(?:be )?(?:loaded|found)"
    r"|(?:unable|failed) to (?:locate|load|find|get)[^\n]{0,20}credential"
    r"|could not (?:locate|load|find)[^\n]{0,20}credential"
    r"|permission denied \(publickey"
    r"|could not read username|terminal prompts disabled"
    r"|\bE401\b|\bENEEDAUTH\b|need auth"
    r"|(?:secret|token|password|api[_ -]?key|credential)s?\b[^\n]{0,40}"
    r"(?:is (?:not set|empty|missing|required)|not (?:set|provided|found)"
    r"|missing|required|empty)"
    r"|(?:missing|empty|no|invalid|expired)\b[^\n]{0,20}"
    r"(?:secret|token|password|api[_ -]?key|credential)"
    r"|access denied|not authorized|unauthenticated"
    r"|login (?:failed|required)",
    re.I)

# The network, or something the image does not carry. Distinct from
# RUNNER_LIMIT only so the output can say which, and read the same way:
# proves nothing. A registry refusing on *auth* grounds is a credential
# failure and is caught above; a registry that was merely unreachable is this.
# Wrong direction: toward claiming nothing.
ENVIRONMENT_LIMIT = re.compile(
    r"temporary failure in name resolution|could not resolve host"
    r"|name or service not known|\bEAI_AGAIN\b"
    r"|connection (?:refused|reset|timed out)|\bECONNREFUSED\b|\bETIMEDOUT\b"
    r"|network is unreachable|\bENETUNREACH\b"
    r"|the requested url returned error: 5\d\d"
    r"|\b5\d\d (?:internal server error|bad gateway|service unavailable)\b"
    r"|: command not found|: not found\s*$"
    r"|no such file or directory"
    r"|unable to locate package|\bE: Package\b"
    r"|read error|tls handshake|certificate (?:verify|has expired)"
    r"|could not (?:install|download)[^\n]{0,40}(?:timed out|timeout)",
    re.I)

# A check produced findings, or the project's own code did not build or pass.
# A POSITIVE pattern, required before anything is read as having executed:
# this is the only table whose match pushes a repository toward the answer, so
# every entry is a signature that means a project command ran and reached a
# verdict of its own. A build failing for want of an unreachable dependency is
# deliberately not here; it reads as an environment failure, because an
# inaccessible dependency and a credentialled one look the same from outside.
MERIT_FAILURE = re.compile(
    r"\bassertionerror\b|\bassert(?:ion)? failed\b|\bexpected\b[^\n]{0,30}"
    r"\b(?:but|to (?:be|equal))\b"
    r"|tests? (?:run|failed|failing)[: ]|\d+ (?:test|spec)s? failed"
    r"|failures: [1-9]|failures=[1-9]|\berrors: [1-9]"
    r"|test result: FAILED|^--- FAIL|^=== FAIL|\bFAIL\b[^\n]{0,60}\.(?:ts|js|py|go|rb)"
    r"|\b\d+ (?:failed|failing)\b"
    r"|compilation (?:error|failed)|\berror TS\d+\b|\bSyntaxError\b"
    r"|\bcannot find (?:symbol|module|name)\b|\bundefined reference\b"
    r"|\bwould reformat\b|\breformatted\b|code style|\bERROR:? ?[A-Z]\d{3}\b"
    r"|\bE\d{3}\b[^\n]{0,60}line too long"
    r"|\bproblems? \(\d+ errors?"
    r"|\beslint\b[^\n]{0,40}\berror\b|\bflake8\b|\bruff\b[^\n]{0,20}failed"
    r"|execution failed for task '"
    r"|BUILD FAILED|BUILD FAILURE|\bFAILURE: Build (?:failed|completed)"
    r"|\bhook(?:s)? (?:failed|modified)|\bFailed\b[^\n]{0,20}hook",
    re.M | re.I)

# The step name a local runner prints for a step that is an action rather than
# the project's own command. `ran-with-failures` requires a project command, so
# a merit-looking string in an action's output cannot produce that reading on
# its own.
ACTION_STEP_NAME = re.compile(r"^[\w.-]+/[\w.-]+@|^(?:\./|docker://)")

# ------------------------------------------------------------ the guards

# Above this, refuse unless the environment says otherwise. The ceiling is low
# because the thing being multiplied is not a request but a container running
# somebody else's build, so the cost of a typo is hours and the consent
# question scales with it. The ceiling stops the typo, not the decision, which
# is the same shape the GitLab sample ceiling has.
SAMPLE_CEILING = 12
LARGE_SAMPLE_ENV = "ALLOW_LARGE_SAMPLE"

# The per-repository budget, shared across that repository's workflow files.
# 20 minutes, chosen against measurement rather than taste: on an ARM host the
# runner image is amd64 and runs under emulation, where a dependency install
# that takes a minute natively takes several, and the first run of a corpus
# also pays for the image pull. A budget tight enough to cut a real run turns
# a measurement into a measurement of the host, so it is generous and it is
# overridable in both directions.
TIMEOUT_DEFAULT = 1200

# Seconds between clones. The mirror this was built against runs on a
# constrained CPU allocation, and a clone is far more expensive for it than a
# API read. One worker, always: there is no concurrency knob here, because the
# cost being paced is somebody else's instance and the thing after it is a
# container on this host.
CLONE_PACE = 5.0

# ------------------------------------------------------------ the disk
#
# THE RISK IS NOT THIS HARNESS'S OWN APPETITE. The tooling is measured: the
# runner image is 1.63 GB and the `act-toolcache` volume it fills is 1.57 GB,
# so roughly 3.2 GB before a single repository has been run, and transient
# container layers per repository on top. That is small. What is not small is
# the machine it lands on: the host this was developed against carried 60 GB of
# images, 58 GB of volumes and 47 GB of build cache from work that has nothing
# to do with this tool, against 54 GB of free space. Starting a multi-hour run
# there is how a measurement ends with no results and somebody else's build
# broken by a full disk.
#
# So there is a floor, it refuses before the first repository, and it is
# re-read between repositories. It sits well above the 3.2 GB the tooling
# needs, and the margin is the point:
#
#   3.2 GB  the tooling, paid once, before anything useful has happened
#   ~2 GB   one repository's transient layers, plus what the toolcache keeps of
#           a toolchain version it has not seen. Containers are removed per
#           workflow so these do not accumulate, but one of them has to fit
#   rest    margin, because this is somebody's working machine. A measurement
#           instrument that drives a shared disk to its last gigabyte has
#           broken something it was never asked to touch
#
# It is a floor and not a budget. A sample whose repositories each want a
# different toolchain can need several times this, which is why the figure is
# re-read between repositories rather than trusted once at the start.
#
# And it is a floor under GROWTH HEADROOM, not under the daemon's internal free
# space: see disk_headroom() for what that costs and why no container is
# started to get the better figure.
DISK_FLOOR = 10 * 1000 ** 3
LOW_DISK_ENV = "ALLOW_LOW_DISK"

# How long the daemon is given to answer a question about itself. Short,
# because these are local reads, and a preflight that hangs is worse than one
# that falls back to the host figure and records that it did.
DOCKER_ASK_TIMEOUT = 20

DOCKER = "docker"

# EVERY DOCKER COMMAND THIS MODULE RUNS, named here and nowhere else. Both are
# reads. docker_read() refuses anything absent from this table, so "this tool
# never changes a Docker object" is a property of a list a reader checks in one
# glance rather than of a habit spread over a module.
DOCKER_READ_ONLY = {
    "root": ("info", "--format", "{{.DockerRootDir}}"),
    "usage": ("system", "df", "--format", "{{json .}}"),
}

# Where Docker Desktop keeps the VM's disk image on macOS. Needed because the
# daemon's own root directory is inside that VM and does not exist on this
# filesystem at all, so asking the host about it answers a different question.
VM_DISK_IMAGE = (
    "~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw",
    "~/Library/Containers/com.docker.docker/Data/vms/0/Docker.raw",
)

READ_FROM_ROOT = "the daemon's own storage directory, {}"
READ_FROM_IMAGE = "the daemon's VM disk image, {}"
READ_FROM_HOST = "the host filesystem at {}"

IMAGE_LIMITATION = (
    "HOW MUCH FURTHER THE VM IMAGE COULD GROW, not how much room is left "
    "inside it. The VM's disk image is sparse, so what is reported is the "
    "remainder of its declared size that the VM has never written, capped by "
    "the host filesystem the image grows into; a block the VM has since freed "
    "may still be allocated on the host and is counted as used here. It "
    "therefore errs toward refusing a run that would have fitted, and it says "
    "nothing at all about the free space the daemon sees inside its own "
    "filesystem.")

# Printed and recorded beside every reading, because the whole figure is
# growth headroom and a reader will otherwise take it for free space.
HEADROOM_LIMITATION = (
    "WHAT THIS GUARD PROTECTS AGAINST IS FILLING THE HOST. It does not detect "
    "a daemon that is internally full: the figure is how much further the "
    "daemon's storage can grow into the disk underneath it, not how much room "
    "is left inside the filesystem the daemon writes images, volumes and "
    "container layers to. Those two differ, and in the direction that matters "
    "here, so a daemon whose own filesystem is full while the host still has "
    "room passes this preflight. The symptom of that case is a run that fails "
    "on a write with the preflight having said yes.")
HOST_LIMITATION = (
    "THE DAEMON'S OWN FIGURE COULD NOT BE READ, so this is the host "
    "filesystem and not the disk the containers are written to. The two differ "
    "whenever the daemon runs in a VM or on another machine, and in that case "
    "the host figure can be generous by any amount. Why it could not be read: "
    "{}")
NO_FIGURE_LIMITATION = (
    "NEITHER THE DAEMON NOR THE HOST COULD BE READ, so there was no figure to "
    "refuse on and the run was not stopped by one. Treat the run as having "
    "had no disk preflight at all. Why: {}")

RECLAIM_ADVICE = (
    "Reclaiming is yours to decide and this tool never does it: a measurement "
    "instrument that deleted the operator's data would be a worse failure than "
    "a run that declined to start. `docker system df` lists what is there. "
    "`docker image prune -a` removes unused images and `docker builder prune` "
    "removes the build cache; both only cost a rebuild. `docker volume prune` "
    "is the dangerous one, because a volume can hold the only copy of "
    "something.")

DISK_COMMENT = (
    "The container daemon's growth headroom at the start and at the end of "
    "the run, so a reader can see what it cost. NOT the free space the daemon "
    "sees inside its own filesystem: this guard protects against filling the "
    "host, and a daemon that is internally full while the host still has room "
    "passes it, the symptom being a run that fails on a write although the "
    "preflight said yes. `read_from` says which reading it is: the daemon's "
    "own storage directory is the filesystem's own free space, a VM disk image "
    "is how much further that image could grow, and the host filesystem is a "
    "substitute reported only when nothing better could be read. `limitation` "
    "carries that caveat verbatim. "
    "`stopped_early` is set when the floor was reached between repositories "
    "and the run stopped with the results it had, which is why the "
    "distribution above may cover fewer repositories than were selected. "
    "Nothing was deleted to make room: this tool reads Docker's figures and "
    "never changes a Docker object.")

# Environment variables not handed to the runner. A credential-shaped name is
# dropped whatever it holds. The local runner does not forward its own
# environment into the workflow container, so this is belt and braces rather
# than the mechanism; the mechanism is that no secret is passed and no secret
# file is read. DOCKER_* survives, because the runner needs it to reach the
# daemon and pull an image, and an image pull is not the workflow.
CREDENTIAL_ENV = re.compile(
    r"TOKEN|SECRET|PASSWD|PASSWORD|CREDENTIAL|_KEY|KEY_|APIKEY"
    r"|^(?:AWS|GCP|GOOGLE|AZURE|NPM|PYPI|GH|GITHUB|GITLAB|SSH|OP|VAULT)_"
    r"|^(?:GH|GITHUB|GITLAB)_|AUTH", re.I)
CREDENTIAL_ENV_KEEP = re.compile(r"^DOCKER_")

MIRROR_CLONE = "https://git.opencode.swiss/{}.git"

# ------------------------------------------------------------ the runner
#
# The local runner's own version is a measurement input and not a detail of
# the install, which is why it is resolved here and recorded in the output.
# Two things made it one.
#
# A runner older than this refuses every action built on a modern Node
# runtime: "The runs.using key in action.yml must be one of: [composite docker
# node12 node16], got node20". That is not a pipeline that needed a secret and
# it is not even a pipeline that failed; it is the runner declining to start.
# A corpus measured with such a runner would report `environment-failure` for
# every repository whose workflow calls an action released after about 2023,
# which is nearly all of them, and the distribution would look like a finding.
# So the floor is enforced rather than documented.
#
# And a host can carry more than one: a version per package manager, each on
# PATH, resolved by whichever directory comes first. Picking the newest rather
# than the first is the difference between measuring the corpus and measuring
# the PATH order.
RUNNER = "act"
# The one event the runner is given, named here because two places depend on
# it: the command line it is invoked with, and the selection rule that refuses
# a scope holding nothing this event can start. Letting those drift is how a
# repository gets cloned for a run that could not have begun.
RUNNER_EVENT = "pull_request"
# A reusable workflow is declared, not triggered. The runner has no way to
# invoke one standalone, whatever event it is handed.
REUSABLE_TRIGGER = "workflow_call"
RUNNER_MIN = (0, 2, 50)
RUNNER_MIN_REASON = (
    "older runners refuse every action built on a Node runtime newer than "
    "node16, which would report an environment failure for nearly every "
    "repository in any current corpus and read as a finding")

# ------------------------------------------------------------ selection

# Recorded in the output verbatim, because a reader meeting a distribution of
# six outcomes over eight repositories needs the rule before the numbers.
SELECTION_RULE = [
    "the pull-request scope has a pipeline (its primary class is neither "
    "no-pipeline nor no-pull-request-trigger)",
    "not an organisation profile repository: a `.github` or equivalent "
    "repository holds no software, and the corpus denominator leaves it out "
    "already",
    "static reading left it unresolved: the pull-request scope carries "
    "credentials-unclear or test-step-unidentified, which are the two bands "
    "execution exists to narrow",
    "special-env in neither scope, because a Windows, macOS, GPU or "
    "self-hosted runner is not a thing a local runner can provide",
    "every file in the pull-request scope is a GitHub Actions workflow, "
    "because the runner reads no other grammar",
    "no text in those files asking for an excluded environment: a Windows or "
    "macOS runner image, a self-hosted label, or nested virtualisation",
    "something the runner's own event can start: a scope whose every file is "
    "a workflow_call reusable workflow cannot be invoked standalone, and a "
    "scope where no file declares the pull-request event leaves the runner no "
    "job to find. Both fail in a tenth of a second and both are decidable "
    "from the cached text, so neither is cloned",
    "a recognised toolchain among the scope's signals (node, python, go or "
    "java), so a first sample is spent on cases where a failure is "
    "interpretable",
    "at most one repository per owner, so the sample is not one team's house "
    "style measured eight times",
    "ordered by workflow-file count, then by total text length, then by name, "
    "and the first N taken",
]
SELECTION_CAVEAT = (
    "NOT A SAMPLE OF THE CORPUS AND NOTHING HERE EXTRAPOLATES TO IT. The rule "
    "selects for what a local runner can execute and for cases where a "
    "failure can be read, which is a selection on exactly the properties "
    "under measurement. It is chosen for signal on a first run, not for "
    "coverage: the figures below describe these repositories and no "
    "population.")

UNRESOLVED = (CREDENTIALS_UNCLEAR, TEST_STEP_UNIDENTIFIED)
ABSENT = (NO_PIPELINE, NO_PULL_REQUEST_TRIGGER)
WANTED_TOOLCHAINS = (TOOLCHAIN_PREFIX + "node", TOOLCHAIN_PREFIX + "python",
                     TOOLCHAIN_PREFIX + "go", TOOLCHAIN_PREFIX + "java")
# What the runner cannot provide, read off the workflow text rather than only
# off `special-env`, because the two disagree at the margin and the cost of a
# miss here is a container that cannot start. Wrong direction: it drops
# candidates that would have run, which costs coverage and no claim.
EXCLUDED_ENV = re.compile(
    r"windows-(?:latest|\d)|macos-(?:latest|\d)|\bself-hosted\b"
    r"|runs-on:\s*\[?\s*['\"]?(?:windows|macos)"
    r"|docker:[\d.]*-?dind|\bdind\b|--privileged|/dev/kvm|qemu-system"
    r"|\bvagrant\b|nested-virt", re.I)

# The funnel's own keys, named rather than spelled at each site, so a reason
# the checks assert on and a reason the output records cannot drift apart.
DROP_PROFILE_REPO = "an organisation profile repository, not software"
DROP_REUSABLE_ONLY = (
    "every workflow is a reusable workflow the runner cannot invoke")
DROP_NO_RUNNER_EVENT = (
    "no workflow declares the pull-request event the runner is given")


def workflow_paths(profile_scope):
    """The pull-request scope's GitHub Actions workflow files."""
    return [p for p in profile_scope.get("files", [])
            if "/workflows/" in p]


def unrunnable_scope(workflows, texts):
    """Why the runner could not start this scope at all, or None.

    THE FAILURE IS CERTAIN AND IT IS CERTAIN BEFORE THE CLONE. A scope with
    nothing the runner's one event can start exits in a tenth of a second with
    "Could not find any stages to run", which is recorded as an environment
    failure and claims nothing. A measured run of 19 repositories spent nine of
    its records that way, on two repositories. Both were decidable from the
    cached pipeline text, so both belong in the funnel as a drop with a reason
    rather than in the distribution as a mystery.

    Two readings, in this order, because the causes differ. A reusable
    workflow cannot be invoked standalone whatever event is handed to the
    runner, and that is worth saying on its own; anything else here is a scope
    whose files declare some other event, `pull_request_target` being the one
    that occurs, which the runner would need a different invocation to reach.

    THE WHOLE SCOPE IS THE UNIT, not the file: one `pull_request` workflow
    beside four reusable ones has something to run, and the four are the
    callees. And an unreadable `on:` keeps the benefit of the doubt, for the
    reason structure.in_pull_request_scope() gives it: a file that did not say
    so in a shape either reading handles is not a file to drop on a guess.
    """
    triggers = [actions_triggers(strip_comments(texts.get(p, "")))
                for p in workflows]
    if not triggers or any(t is None for t in triggers):
        return None
    if any(RUNNER_EVENT in t for t in triggers):
        return None
    if all(REUSABLE_TRIGGER in t for t in triggers):
        return DROP_REUSABLE_ONLY
    return DROP_NO_RUNNER_EVENT


def select(profile, cache, sample):
    """(chosen, rejections) for a sample of `sample` repositories.

    `chosen` is a list of dicts, in the order they will be run. `rejections`
    counts how many candidates each rule took out, which is what makes the
    rule arguable instead of a black box: a reader can see that the toolchain
    filter did most of the narrowing and disagree with it.
    """
    rejected = {}

    def drop(rule):
        rejected[rule] = rejected.get(rule, 0) + 1

    rows = []
    for key, prof in sorted(profile.get("repos", {}).items()):
        pr = prof.get(PR_SCOPE, {})
        if pr.get("primary") in ABSENT:
            continue                      # not a candidate at all, not a drop
        if key.split("/")[-1] in PROFILE_REPO_NAMES:
            drop(DROP_PROFILE_REPO)
            continue
        flags = set(pr.get("flags", []))
        if not flags & set(UNRESOLVED):
            drop("resolved by static reading")
            continue
        if SPECIAL_ENV in flags or SPECIAL_ENV in set(
                prof.get(REPO_SCOPE, {}).get("flags", [])):
            drop("special-env")
            continue
        scope_files = pr.get("files", [])
        workflows = workflow_paths(pr)
        if not workflows or len(workflows) != len(scope_files):
            drop("not entirely GitHub Actions")
            continue
        texts = cache.get("repos", {}).get(key, {}).get("files", {})
        joined = "\n".join(texts.get(p, "") for p in workflows)
        if EXCLUDED_ENV.search(joined):
            drop("asks for an environment the runner cannot provide")
            continue
        unrunnable = unrunnable_scope(workflows, texts)
        if unrunnable:
            drop(unrunnable)
            continue
        signals = set(pr.get("signals", []))
        if not signals & set(WANTED_TOOLCHAINS):
            drop("no recognised toolchain")
            continue
        rows.append({
            "repo": key,
            "owner": key.split("/")[0],
            "primary": pr.get("primary"),
            "unresolved": sorted(flags & set(UNRESOLVED)),
            "workflows": workflows,
            "bytes": len(joined),
            # Whether a command form the static rules recognise as a test
            # invocation is in the scope at all. A clean run over a scope
            # where this is false is evidence about the pull-request check and
            # not about a test suite, and conflating the two would be the
            # whole error this instrument exists to avoid.
            "test_invocation_recognised": bool(TEST_INVOCATION.search(joined)),
        })

    rows.sort(key=lambda r: (len(r["workflows"]), r["bytes"], r["repo"]))
    chosen, seen_owners = [], set()
    for row in rows:
        if len(chosen) >= sample:
            break
        if row["owner"] in seen_owners:
            drop("a second repository from one owner")
            continue
        seen_owners.add(row["owner"])
        chosen.append(row)
    return chosen, rejected


def require_sample(sample, allow_large=None):
    """Refuse unless the size was given explicitly and is small enough.

    Two refusals, stopping two different accidents. A missing size stops the
    one that matters: there is no default, because this executes third-party
    code and the amount of it is always somebody's explicit decision. A size
    above the ceiling stops the typo, and is overridable, because a larger
    deliberate run is a decision somebody is allowed to make in writing.
    """
    if allow_large is None:
        allow_large = os.environ.get(LARGE_SAMPLE_ENV, "") not in ("", "0")
    if not sample:
        return ("--sample takes a size: how many repositories to execute. "
                "There is deliberately no default, because every one of them "
                "runs third-party code on this machine.")
    if sample < 0:
        return "--sample takes a positive size"
    if sample > SAMPLE_CEILING and not allow_large:
        return ("--sample {} is above the {}-repository ceiling for executing "
                "third-party pipelines. Re-run with {}=1 if that is "
                "deliberate.".format(sample, SAMPLE_CEILING, LARGE_SAMPLE_ENV))
    return None


# ------------------------------------------------------------ the disk check


def gb(count):
    """Bytes in the same GB the daemon's own output uses, for an operator."""
    return "unknown" if count is None else "{:.1f} GB".format(
        count / 1000.0 ** 3)


def low_disk_allowed(environ=None):
    """Whether the operator has said in writing to proceed below the floor."""
    environ = os.environ if environ is None else environ
    return environ.get(LOW_DISK_ENV, "") not in ("", "0")


def docker_read(what, run=None, docker=DOCKER):
    """One allowlisted read-only docker command. (text, why it failed).

    The allowlist is the guard. A name absent from DOCKER_READ_ONLY is refused
    before anything is spawned, so a later call that wanted to free some room
    has nowhere to go: this module reads Docker's figures and changes no Docker
    object, and that is enforced here rather than promised in a comment.

    `run` is the injection point for the whole of "ask the daemon something",
    so the checks can drive the preflight without a daemon on the machine.
    """
    if what not in DOCKER_READ_ONLY:
        return "", "not a read-only docker command: {!r}".format(what)
    argv = [docker] + list(DOCKER_READ_ONLY[what])
    if run is None:
        def run(argv):
            try:
                proc = subprocess.run(argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL,
                                      timeout=DOCKER_ASK_TIMEOUT)
            except (OSError, subprocess.SubprocessError) as e:
                return None, "`{}` did not run: {}".format(argv[0], e)
            if proc.returncode != 0:
                return None, "`{}` exited {}".format(
                    " ".join(argv), proc.returncode)
            return proc.stdout.decode("utf-8", "replace"), ""
    text, reason = run(argv)
    return (text or ""), (reason or "")


def disk_headroom(scratch=None, run=None, images=VM_DISK_IMAGE):
    """(bytes of growth headroom, how it was read, the limitation).

    GROWTH HEADROOM IS NOT THE DAEMON'S INTERNAL FREE SPACE, and the name is
    the claim. What this measures is how much further the daemon's storage can
    grow into the disk underneath it. The guard built on it protects against
    filling the host; it does not detect a daemon that is internally full,
    which passes the preflight and then fails on a write. HEADROOM_LIMITATION
    says so wherever the figure is reported, because a figure called
    "available" would be read as the thing this cannot measure.

    THE HOST FIGURE IS THE WRONG ANSWER and is the last resort here. What
    fills during a run is the filesystem the daemon writes images, volumes and
    container layers to, and on macOS that is a disk inside a VM: a host with
    room to spare says nothing about whether the next image pull fits, and a
    preflight that read the host would wave through exactly the run this
    exists to stop.

    So the daemon is asked where its root is, and three readings are possible,
    in descending order of how close each comes to the question. If the root
    directory is on this filesystem, that is the daemon's own disk and its
    free space is the figure. If it is not, the daemon is in a VM, and the
    VM's sparse disk image says how much further it could grow, which is the
    reading that is headroom and not free space. If neither can be read, the
    host filesystem is reported with the substitution stated in the limitation
    rather than passed off as the daemon's figure.

    NO CONTAINER IS LAUNCHED TO READ THE BETTER FIGURE, and that is deliberate
    rather than an omission. The daemon's internal free space can be had by
    running a container and asking its filesystem. This module creates no
    Docker object of any kind: DOCKER_READ_ONLY is every command it issues,
    docker_read() refuses anything absent from that list, and the checks
    assert both the list and the argv the preflight actually spends. That
    property is worth more than the better number. It is what makes this
    module safe to point at somebody's working machine, it is checkable in one
    glance at DOCKER_READ_ONLY, and a preflight that started containers to
    measure a disk would be claiming an exemption from the rule the rest of
    the module keeps. So the limitation is published instead.
    """
    scratch = tempfile.gettempdir() if scratch is None else scratch
    host, host_reason = None, ""
    try:
        host = shutil.disk_usage(scratch).free
    except OSError as e:
        host_reason = str(e)

    text, reason = docker_read("root", run=run)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    root = lines[0] if lines else ""
    if root and os.path.isdir(root):
        try:
            return shutil.disk_usage(root).free, READ_FROM_ROOT.format(root), ""
        except OSError as e:
            reason = "the daemon's root directory {} could not be read: {}" \
                .format(root, e)

    for candidate in images:
        path = os.path.expanduser(candidate)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        blocks = getattr(stat, "st_blocks", None)
        if blocks is None:
            continue
        headroom = max(0, stat.st_size - blocks * 512)
        if host is not None:
            headroom = min(headroom, host)
        return headroom, READ_FROM_IMAGE.format(path), IMAGE_LIMITATION

    why = reason or (
        "the daemon's root directory is {}, which is not on this filesystem"
        .format(root) if root else "the daemon named no root directory")
    if host is None:
        return None, "nothing readable", NO_FIGURE_LIMITATION.format(
            "; ".join(p for p in (why, host_reason) if p))
    return host, READ_FROM_HOST.format(scratch), HOST_LIMITATION.format(why)


def require_disk(headroom, floor=DISK_FLOOR, allow_low=None):
    """Refuse a run the disk has no room to grow into. The reason, or None.

    The message carries the floor, what was found and the difference between
    them, because "not enough space" sends the operator to go and measure
    something this function has already measured. It carries the limitation
    too: the figure it refuses on is growth headroom, so a refusal is about
    the host filling up and a pass is not a statement that the daemon has room
    inside its own filesystem. The escape hatch is named in it for the same
    reason the sample ceiling names its own: the floor stops an accident, and
    a deliberate run on a tight disk is a decision somebody is allowed to make
    in writing.

    An unreadable figure does not refuse. There is nothing to refuse on, and
    guessing in either direction would be worse than saying so, which
    disk_headroom() has already done in its limitation.
    """
    if allow_low is None:
        allow_low = low_disk_allowed()
    if headroom is None or headroom >= floor or allow_low:
        return None
    return ("only {} of growth headroom is left for the container daemon, "
            "below the {} floor this mode needs. Free {} more, or re-run with "
            "{}=1 if running on a disk this tight is deliberate. {}".format(
                gb(headroom), gb(floor), gb(floor - headroom),
                LOW_DISK_ENV, HEADROOM_LIMITATION))


def reclaimable(run=None):
    """[(kind, size, reclaimable)] out of the daemon's own usage report.

    Quoted rather than recomputed: these are Docker's own pre-formatted
    figures, and an arithmetic of our own over them would invent a precision
    that the overlap between images and build cache does not support.
    """
    text, _reason = docker_read("usage", run=run)
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("Type"):
            rows.append((row.get("Type"), row.get("Size", "?"),
                         row.get("Reclaimable", "?")))
    return rows


def reclaim_report(run=None):
    """What could be freed, and whose decision it is. Printed, never acted on.

    The operator is the one who owns the machine and the data on it. So this
    says what is there and which command removes it, and stops: an instrument
    that pruned somebody's volumes to make room for its own measurement would
    have destroyed data nobody asked it to touch, and a full disk is the
    cheaper of the two failures.
    """
    rows = reclaimable(run=run)
    if not rows:
        return RECLAIM_ADVICE
    lines = ["what the daemon reports is there:"]
    for kind, size, free_able in rows:
        lines.append("  {:<16} {:>10}, of which {} reclaimable".format(
            kind, size, free_able))
    return "\n".join(lines) + "\n" + RECLAIM_ADVICE


# ------------------------------------------------------------ the runner call


def scrubbed_env(environ=None):
    """The environment handed to the runner, with credentials taken out."""
    environ = os.environ if environ is None else environ
    return {k: v for k, v in environ.items()
            if CREDENTIAL_ENV_KEEP.match(k) or not CREDENTIAL_ENV.search(k)}


def runner_version(text):
    """The version tuple out of the runner's own `--version` line, or None."""
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in found.groups()) if found else None


def find_runner(search=None, ask=None):
    """(path, version tuple, version text), or (None, None, reason).

    The NEWEST runner on PATH, not the first. A host carrying two installs
    resolves to whichever directory happens to come first, and that is the
    PATH order deciding what the measurement says.
    """
    search = (os.environ.get("PATH", "") if search is None else search)
    if ask is None:
        def ask(path):
            """The runner's own `--version`, or "" if it is not one.

            Existence lives in here rather than in the loop so that the whole
            of "is there a runner at this path, and which version" has one
            injection point. A check that had to plant executables on the
            filesystem to exercise the version floor would be a check nobody
            runs.
            """
            if not os.access(path, os.X_OK) or os.path.isdir(path):
                return ""
            try:
                proc = subprocess.run([path, "--version"],
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT)
                return proc.stdout.decode("utf-8", "replace").strip()
            except OSError:
                return ""
    best = None
    for directory in search.split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, RUNNER)
        text = ask(candidate)
        version = runner_version(text)
        if version and (best is None or version > best[1]):
            best = (candidate, version, text[:120])
    if best is None:
        return None, None, (
            "no `{}` on PATH. This mode needs a local GitHub Actions runner; "
            "USAGE.md says what to install.".format(RUNNER))
    if best[1] < RUNNER_MIN:
        return None, None, (
            "`{}` {} is below the {} floor, and {}. Install a newer one; if "
            "the host carries two, both directories have to be on PATH, "
            "because the newest is the one used.".format(
                RUNNER, ".".join(str(n) for n in best[1]),
                ".".join(str(n) for n in RUNNER_MIN), RUNNER_MIN_REASON))
    return best


def runner_argv(clone, workflow, arch="linux/amd64", runner=RUNNER):
    """The exact command line, built in one place so it can be asserted on.

    Three of these flags are the experiment rather than configuration, and
    none of them is reachable from this module's own command line:

    `--secret-file os.devnull` is the one that matters. The runner's DEFAULT is
    to read `.secrets` from the working directory, and the working directory
    here is a clone of somebody else's repository, so leaving it at the
    default would let a file inside the corpus supply secrets to the very
    experiment that is meant to have none. Pointing it at the null device
    makes a secret file impossible rather than merely absent.

    `--env-file os.devnull` for the same reason, one default down: `.env` in
    the clone would otherwise be read.

    `--container-daemon-socket os.devnull` withholds the host's container
    daemon from the workflow container. The runner mounts the real socket by
    default, which hands a third-party pipeline control of the daemon running
    it. The null device is what is given instead of the socket rather than
    instead of the flag: the runner's own spelling for "do not mount it" is
    rejected as a volume name by current daemons, so the mount is made and
    pointed somewhere harmless. A pipeline that genuinely needs a daemon then
    fails, and fails as an environment failure, which claims nothing. That is
    the right trade: an honest "proves nothing" costs a reading, and a mounted
    socket costs the host.
    """
    return [
        runner, RUNNER_EVENT,
        "-C", clone,
        "-W", workflow,
        "--secret-file", os.devnull,
        "--env-file", os.devnull,
        "--container-daemon-socket", os.devnull,
        "--container-architecture", arch,
        "--rm",
    ]


def assert_no_secret(argv):
    """The guard that cannot be left to review: argv supplies no secret.

    Checked at every call site rather than trusted from `runner_argv`, so a
    later flag that threaded a secret through has somewhere to fail. Returns
    None, or the reason it refused.
    """
    for i, part in enumerate(argv):
        if part in ("-s", "--secret") or part.startswith("--secret="):
            return "a secret was passed to the runner: " + part
        if part == "--secret-file":
            if i + 1 >= len(argv) or argv[i + 1] != os.devnull:
                return ("the runner's secret file is not the null device: "
                        + " ".join(argv[i:i + 2]))
        if part.startswith("--secret-file=") and \
                part.split("=", 1)[1] != os.devnull:
            return "the runner's secret file is not the null device: " + part
    if "--secret-file" not in argv:
        return ("the runner was called without --secret-file, so it would "
                "read a secret file out of the clone")
    return None


# ------------------------------------------------------------ reading the log

# How the local runner announces a step and its result. Three details of the
# real format, each of which silently breaks the reading if it is missed.
#
# Matched on the WORDS and not on the emoji beside them. The emoji are
# decoration and have moved between releases; "Run", "Success - " and
# "Failure - " are what the runner's own tests assert.
#
# The RESULT line carries a duration the start line does not
# ("Success - Main npm ci [1m1.86s]"), so pairing a result with its step by
# name needs the duration stripped. Leave it on and no step is ever paired,
# every run looks like one where nothing finished, and the whole corpus reads
# as an environment failure.
#
# And the PHASE IS OPTIONAL. A step has a Main phase and may have Pre and
# Post; the job envelope's own entries ("Run Complete job") carry none. The
# envelope is recorded like anything else and then held out of the merit
# reading, because a failure there is the runner's bookkeeping and not the
# project's command.
STEP_START = re.compile(r"^\[(?P<job>[^\]]*)\]\s+\S*\s*"
                        r"Run (?:(?P<phase>Main|Pre|Post) )?(?P<name>.+?)\s*$")
STEP_RESULT = re.compile(r"^\[(?P<job>[^\]]*)\]\s+\S*\s*"
                         r"(?P<result>Success|Failure) - "
                         r"(?:(?P<phase>Main|Pre|Post) )?(?P<name>.+?)"
                         r"(?:\s+\[[^\]]*\])?\s*$")


def read_steps(log):
    """[{job, phase, name, result, output}] in the order the runner ran them.

    `output` is the lines between a step's start and its result, which is what
    the credential table is matched against. Matching that table against the
    whole log instead was the first thing tried and it is wrong: a cache
    warning from an earlier step reads as the failing step's own missing
    token, and `secret-required` is the one reading that must not be given
    away.
    """
    steps, current = [], None
    for line in log.splitlines():
        start = STEP_START.match(line)
        if start:
            current = {"job": start.group("job"),
                       "phase": start.group("phase"),
                       "name": start.group("name"),
                       "result": None,
                       "output": []}
            steps.append(current)
            continue
        done = STEP_RESULT.match(line)
        if done:
            for step in reversed(steps):
                if (step["result"] is None
                        and step["name"] == done.group("name")
                        and step["phase"] == done.group("phase")):
                    step["result"] = done.group("result")
                    break
            current = None
            continue
        if current is not None:
            current["output"].append(line)
    for step in steps:
        step["output"] = "\n".join(step["output"])
    return steps


def first_failure(steps):
    """The first step the runner reported as having failed, or None."""
    for step in steps:
        if step["result"] == "Failure":
            return step
    return None


def classify_outcome(exit_code, log, timed_out=False, started=True):
    """(outcome, reason, evidence_line) for one workflow file's run.

    THE ORDER OF THE TESTS IS THE DESIGN. Read downward:

    1. A budget that ran out says nothing about privilege.
    2. A run where no step ever started never reached the pipeline.
    3. Exit zero with no failing step is the positive case, and it is the
       only class that does not consult a pattern table.
    4. The runner's own inability comes BEFORE the credential table, because
       the two overlap on rejections that belong to the runner's unauthenticated
       access to a public API and not to the project.
    5. The credential table, against the failing step's own output only.
    6. The network and the image.
    7. A positive merit signature AND a failing step that is the project's own
       command, which is the only way a failure is read as having executed.
    8. Anything else: `environment-failure`, which claims nothing. This is the
       default on purpose. Every unrecognised failure lands here, so the two
       classes that carry a claim are reached only by a pattern that matched.
    """
    if timed_out:
        return TIMED_OUT, "the per-repository budget ran out", ""
    steps = read_steps(log)
    if not started or not steps:
        return (NOT_ATTEMPTED if not started else ENVIRONMENT_FAILURE,
                "the runner started no step" if started
                else "the repository was never run",
                _evidence(log, RUNNER_LIMIT) or _last_error(log))
    failure = first_failure(steps)
    if exit_code == 0 and failure is None:
        return (RAN_UNPRIVILEGED,
                "every step ran and the job exited zero, with no secret "
                "supplied", "")
    if failure is None:
        # Non-zero with no step blamed: the job envelope failed, not a step.
        return (ENVIRONMENT_FAILURE,
                "the job failed without the runner blaming a step",
                _evidence(log, RUNNER_LIMIT) or _last_error(log))
    where = failure["output"]
    hit = _evidence(where, RUNNER_LIMIT)
    if hit:
        return ENVIRONMENT_FAILURE, "the local runner could not run it", hit
    hit = _evidence(where, CREDENTIAL_FAILURE)
    if hit:
        return (SECRET_REQUIRED,
                "the failing step's own output names a missing, empty or "
                "rejected credential", hit)
    hit = _evidence(where, ENVIRONMENT_LIMIT)
    if hit:
        return (ENVIRONMENT_FAILURE,
                "the environment, not the pipeline: the network, or something "
                "the image does not carry", hit)
    hit = _evidence(where, MERIT_FAILURE)
    if hit and failure["phase"] == "Main" \
            and not ACTION_STEP_NAME.match(failure["name"]):
        return (RAN_WITH_FAILURES,
                "a project command executed and reached a verdict of its own",
                hit)
    return (ENVIRONMENT_FAILURE,
            "the failing step matched nothing this recognises, so it supports "
            "no claim in either direction", _last_error(where) or _last(where))


def _evidence(text, pattern):
    """The first line `pattern` matches, which is what a reader checks."""
    for line in text.splitlines():
        if pattern.search(line):
            return line.strip()[:400]
    return ""


def _last_error(text):
    for line in reversed(text.splitlines()):
        if re.search(r"\berror\b|\bfailed\b|\bfatal\b", line, re.I):
            return line.strip()[:400]
    return ""


def _last(text):
    lines = [l for l in text.splitlines() if l.strip()]
    return lines[-1].strip()[:400] if lines else ""


def aggregate(outcomes):
    """One repository's class from its workflow files' classes."""
    for candidate in AGGREGATE_PRECEDENCE:
        if candidate in outcomes:
            return candidate
    return NOT_ATTEMPTED


# ------------------------------------------------------------ doing it


def clone(repo, into, log=print):
    """Shallow, read-only, from the mirror. True, or False with the reason.

    The mirror rather than the upstream host, for two reasons that point the
    same way: it is infrastructure this project operates, so the load is its
    own to spend, and the upstream host is somebody else's and is not being
    asked for anything by a measurement it did not agree to.
    """
    url = MIRROR_CLONE.format(repo)
    env = dict(scrubbed_env())
    env["GIT_TERMINAL_PROMPT"] = "0"       # never sit waiting for a password
    env["GIT_ASKPASS"] = "true"
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--no-tags", "--single-branch",
         url, into],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    if proc.returncode != 0:
        log("    clone failed: " + proc.stdout.decode(
            "utf-8", "replace").strip().splitlines()[-1][:200])
        return False
    return True


def run_workflow(clone_dir, workflow, budget, arch="linux/amd64",
                 runner=RUNNER, log=print):
    """One workflow file. (outcome, reason, evidence, seconds, log text).

    The runner is invoked with its working directory set to a scratch
    directory that is NOT the clone. That is not tidiness: the runner reads a
    `.actrc` out of its working directory, so running it inside a clone of
    somebody else's repository would let a file in the corpus add flags to the
    command being used to measure it.

    A BUDGET THAT RUNS OUT HAS TO TAKE THE CONTAINER WITH IT. The runner is
    started in a session of its own and, on a timeout, the whole session is
    asked to stop before it is made to: the runner cleans up its container when
    it is asked, and cannot when it is killed outright. The reason this is not
    merely tidy is that the container left behind would go on consuming the
    host while the NEXT repository ran, so a single timeout would quietly
    measure every repository after it under contention.
    """
    argv = runner_argv(clone_dir, workflow, arch=arch, runner=runner)
    refusal = assert_no_secret(argv)
    if refusal:
        sys.exit("refusing to run: " + refusal)
    neutral = tempfile.mkdtemp(prefix="ciprofile-cwd-")
    started = time.time()
    try:
        proc = subprocess.Popen(
            argv, cwd=neutral, env=scrubbed_env(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        shutil.rmtree(neutral, ignore_errors=True)
        return (NOT_ATTEMPTED,
                "the runner would not start: {}".format(e), "",
                round(time.time() - started, 1), "")
    try:
        out, _err = proc.communicate(timeout=budget)
        text = out.decode("utf-8", "replace")
        outcome, reason, evidence = classify_outcome(proc.returncode, text)
    except subprocess.TimeoutExpired:
        out = _stop_session(proc, log=log)
        text = out.decode("utf-8", "replace")
        outcome, reason, evidence = classify_outcome(None, text,
                                                    timed_out=True)
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    return outcome, reason, evidence, round(time.time() - started, 1), text


# How long the runner is given to tear its container down after being asked.
# Short, because it is a `docker rm` and not a build, and bounded because an
# unbounded wait would turn the budget into a suggestion.
STOP_GRACE = 30


def _stop_session(proc, grace=None, log=print):
    """Ask the runner's whole session to stop, then insist. Its output so far.

    THE SIGNAL GOES TO THE PROCESS GROUP, which is the part that matters: the
    runner's own container teardown runs in children of it, and signalling
    only the runner leaves them, and the container, behind. `grace` is a
    parameter so that the escalation can be exercised by a check in seconds
    rather than in minutes.

    AND IT REFUSES TO SIGNAL ITS OWN GROUP. The group signal is only ever
    correct because the runner was started in a session of its own; if it ever
    is not, the group is this process's group and a SIGKILL to it takes the
    whole run down, results and all. That is not a hypothetical: a mutation
    test that removed `start_new_session` killed its own harness, twice,
    before this guard existed. The guard falls back to signalling the one
    process, which leaks a container and is a great deal better than losing
    the run.
    """
    grace = STOP_GRACE if grace is None else grace
    own = os.getpgrp()
    for signal_number, label in ((signal.SIGTERM, "asked"),
                                 (signal.SIGKILL, "killed")):
        try:
            group = os.getpgid(proc.pid)
            if group == own:
                log("    the runner is not in a session of its own; "
                    "signalling it alone rather than this run")
                proc.send_signal(signal_number)
            else:
                os.killpg(group, signal_number)
        except OSError:
            break
        try:
            out, _err = proc.communicate(timeout=grace)
            return out or b""
        except subprocess.TimeoutExpired:
            log("    the runner did not stop when {}; insisting".format(label))
    try:
        out, _err = proc.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        return b""
    return out or b""


def plan(chosen, timeout, arch, runner=RUNNER):
    """What is about to run, printed before anything does.

    A person who asked for eight repositories and is about to have eight
    third-party build scripts execute on their machine should be able to read
    the command, not infer it.
    """
    lines = ["about to execute {} repositories' pull-request workflows "
             "locally, in containers, with NO SECRET SUPPLIED.".format(
                 len(chosen)),
             "this runs third-party code: each pipeline is a script its "
             "maintainers wrote for infrastructure they chose.",
             "budget {}s per repository, {}s between clones, one at a time."
             .format(timeout, CLONE_PACE),
             ""]
    for row in chosen:
        lines.append("  {}  [{}]  {}".format(
            row["repo"], ", ".join(row["unresolved"]),
            " ".join(os.path.basename(w) for w in row["workflows"])))
    lines += ["", "each workflow file runs as:", "  " + " ".join(
        runner_argv("<clone>", "<clone>/<workflow>", arch=arch,
                    runner=runner)), ""]
    return "\n".join(lines)


def execute(chosen, timeout=TIMEOUT_DEFAULT, arch="linux/amd64",
            pace=CLONE_PACE, runner=RUNNER, log=print, space=None,
            floor=DISK_FLOOR, allow_low=None, clone_fn=None, run_fn=None):
    """Run the sample. (records, the interruption that stopped it, or None).

    The clone lives in a temporary directory that is removed in a `finally`,
    including when the runner raised, so a failed run leaves nothing of
    somebody else's repository on the host.

    A RUN THAT STOPS EARLY WITH ITS RESULTS INTACT BEATS ONE THAT DIES WITH
    NONE. The disk is re-read between repositories rather than trusted from
    the preflight, because the preflight measured a machine that was not then
    running containers, and the figure that matters is the one in front of the
    next repository. Below the floor the loop breaks, the records so far are
    returned, and the caller writes them: a sample of four answered
    repositories is a result, and a run killed by a full disk at repository
    five is not. The floor and the escape hatch are the preflight's own, so
    there is one figure to argue with rather than two.

    `space`, `clone_fn` and `run_fn` are injection points, for the same reason
    `find_runner` takes `ask`: a check that had to fill a disk and start a
    container to exercise the stop is a check nobody runs.
    """
    space = (lambda: disk_headroom()[0]) if space is None else space
    clone_fn = clone if clone_fn is None else clone_fn
    run_fn = run_workflow if run_fn is None else run_fn
    records, interruption = [], None
    for i, row in enumerate(chosen):
        if i:
            headroom = space()
            refusal = require_disk(headroom, floor=floor,
                                   allow_low=allow_low)
            if refusal:
                interruption = {
                    "stopped_before": row["repo"],
                    "completed": len(records),
                    "selected": len(chosen),
                    "headroom_bytes": headroom,
                    "headroom": gb(headroom),
                    "reason": refusal,
                }
                log("\nSTOPPING with {} of {} done, results kept: {}".format
                    (len(records), len(chosen), refusal))
                break
            time.sleep(pace)
        log("[{}/{}] {}".format(i + 1, len(chosen), row["repo"]))
        record = dict(row)
        record["runs"] = []
        started = time.time()
        workdir = tempfile.mkdtemp(prefix="ciprofile-diff-")
        try:
            target = os.path.join(workdir, "repo")
            if not clone_fn(row["repo"], target, log=log):
                record["outcome"] = NOT_ATTEMPTED
                record["reason"] = "the clone failed"
                record["seconds"] = round(time.time() - started, 1)
                records.append(record)
                continue
            for workflow in row["workflows"]:
                budget = max(1, timeout - (time.time() - started))
                outcome, reason, evidence, seconds, _text = run_fn(
                    target, os.path.join(target, workflow), budget,
                    arch=arch, runner=runner, log=log)
                log("    {}  {}  ({}s)".format(
                    os.path.basename(workflow), outcome, seconds))
                if evidence:
                    log("      " + evidence[:200])
                record["runs"].append({
                    "workflow": workflow, "outcome": outcome,
                    "reason": reason, "evidence": evidence,
                    "seconds": seconds})
            record["outcome"] = aggregate(
                [r["outcome"] for r in record["runs"]])
            record["reason"] = next(
                (r["reason"] for r in record["runs"]
                 if r["outcome"] == record["outcome"]), "")
            record["seconds"] = round(time.time() - started, 1)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        records.append(record)
    return records, interruption


# ------------------------------------------------------------ the output

COMMENT = (
    "Differential execution: each repository's pull-request workflows were "
    "run locally in a container with NO SECRET SUPPLIED, and the outcome "
    "observed. This is the one figure in this tool that is not signal "
    "detection over pipeline text. "
    "THE MEASURED OUTCOME IS NOT A GREEN RUN. Most pipelines fail under a "
    "local runner for reasons unrelated to privilege, so a green workflow "
    "would measure the runner. The question is whether the check executed, "
    "with nothing granted, without failing for a secret-related reason. "
    "ran-unprivileged (every step ran, exit zero) and ran-with-failures (a "
    "project command executed and failed on its own merits) both answer it: "
    "no privilege was blocking the pipeline. secret-required answers it the "
    "other way, and ONLY where the failing step's own output names a missing, "
    "empty or rejected credential. environment-failure, timed-out and "
    "not-attempted answer nothing and are excluded from every share. "
    "THE POSITIVE CASE IS NOT HEURISTIC AND THE FAILURE CASES ARE. "
    "ran-unprivileged rests on an absence enforced by construction: no secret "
    "file is read, no secret is passed, credential-shaped variables are taken "
    "out of the runner's environment, so nothing could have consumed a secret. "
    "Every other class is a reading of log text, and an unrecognised failure "
    "falls to environment-failure, which supports no claim in either "
    "direction. "
    "`test_invocation_recognised` is the caveat on the scope: where it is "
    "false, no command form the static rules recognise as a test invocation "
    "is in the workflow, so a clean run is evidence about the pull-request "
    "check a contributor triggers and NOT about a test suite behind it. "
    "`selection` carries the rule the sample was chosen by. It is not a "
    "random sample and nothing here extrapolates to any corpus: the rule "
    "selects for what a local runner can execute, which is a selection on the "
    "properties under measurement.")


def write(path, records, selection, meta):
    """The differential-execution output. Returns the path written."""
    refuse_overwrite(path, DIFFERENTIAL_NAME)
    tally = {}
    for record in records:
        tally[record["outcome"]] = tally.get(record["outcome"], 0) + 1
    answered = sum(tally.get(o, 0) for o in ANSWERS)
    out = {
        "$comment": COMMENT,
        "run": date.today().isoformat(),
        "outcomes": {o: tally.get(o, 0) for o in OUTCOMES},
        "answered": answered,
        "proves_nothing": len(records) - answered,
        "selection": selection,
        "repositories": records,
    }
    out.update(meta)
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=False)
        fh.write("\n")
    return path


def summarise(records, log=print, interruption=None):
    """The printed review gate: the outcome table and what it resolved."""
    tally = {}
    for record in records:
        tally[record["outcome"]] = tally.get(record["outcome"], 0) + 1
    log("\noutcomes over {} repositories".format(len(records)))
    for outcome in OUTCOMES:
        if tally.get(outcome):
            log("  {:<22} {:>3}{}".format(
                outcome, tally[outcome],
                "" if outcome in ANSWERS else "   (proves nothing)"))
    answered = sum(tally.get(o, 0) for o in ANSWERS)
    log("\n{} of {} now have an answer static reading did not give"
        .format(answered, len(records)))
    unprivileged = [r for r in records if r["outcome"] in
                    (RAN_UNPRIVILEGED, RAN_WITH_FAILURES)]
    log("  {} ran with nothing granted; {} need a credential".format(
        len(unprivileged), tally.get(SECRET_REQUIRED, 0)))
    blind = [r for r in unprivileged if not r["test_invocation_recognised"]]
    if blind:
        log("  of those that ran, {} hold no command form recognisable as a "
            "test invocation, so the evidence is about the pull-request check "
            "and not about a test suite".format(len(blind)))
    if interruption:
        log("\nTHESE RESULTS ARE PARTIAL. The run stopped before {}, with {} "
            "of {} selected repositories done: {}".format(
                interruption["stopped_before"], interruption["completed"],
                interruption["selected"], interruption["reason"]))
    log("\n" + SELECTION_CAVEAT)


# ------------------------------------------------------------ command line


def build_parser():
    p = argparse.ArgumentParser(
        prog="python3 -m ciprofile.differential",
        description="Run each repository's pull-request workflows locally "
                    "with no secret supplied, and record whether they "
                    "executed. EXECUTES THIRD-PARTY CODE in containers on "
                    "this machine.")
    p.add_argument("--profile", required=True,
                   help="a profile JSON to select the sample from")
    p.add_argument("--cache", required=True,
                   help="the evidence cache holding those repositories' "
                        "pipeline text")
    p.add_argument("--sample", type=int,
                   help="how many repositories to execute. Required, with no "
                        "default, because each one runs third-party code")
    p.add_argument("--timeout", type=int, default=TIMEOUT_DEFAULT,
                   help="per-repository budget in seconds (default %d)"
                        % TIMEOUT_DEFAULT)
    p.add_argument("--arch", default="linux/amd64",
                   help="container architecture. linux/amd64 on an ARM host, "
                        "where the runner images are amd64 and run emulated")
    p.add_argument("--out", default="data",
                   help="directory for " + DIFFERENTIAL_NAME)
    p.add_argument("--dry-run", action="store_true",
                   help="print the selection and the command, run nothing")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    refusal = require_sample(args.sample)
    if refusal:
        return refusal
    for path in (args.profile, args.cache):
        if not os.path.isfile(path):
            return "no such file: " + path
    with open(args.profile) as fh:
        profile = json.load(fh)
    with open(args.cache) as fh:
        cache = json.load(fh)

    chosen, rejected = select(profile, cache, args.sample)
    if not chosen:
        return ("nothing in that profile meets the selection rule; the "
                "rejections were: " + json.dumps(rejected, sort_keys=True))
    runner, version, version_text = find_runner()
    if runner is None and not args.dry_run:
        return version_text
    selection = {
        "rule": SELECTION_RULE,
        "caveat": SELECTION_CAVEAT,
        "requested": args.sample,
        "chosen": len(chosen),
        "rejected_by_rule": rejected,
        "profile": os.path.abspath(args.profile),
        "cache": os.path.abspath(args.cache),
        "clone_from": MIRROR_CLONE.format("<owner>/<name>"),
    }
    print(plan(chosen, args.timeout, args.arch, runner=runner or RUNNER))
    print("runner: {}\n".format(version_text))
    started_with, read_from, limitation = disk_headroom()
    print("container daemon growth headroom: {}  ({})".format(
        gb(started_with), read_from))
    print("  " + HEADROOM_LIMITATION)
    if limitation:
        print("  " + limitation)
    if args.dry_run:
        print("--dry-run: nothing was executed")
        return 0
    refusal = require_disk(started_with)
    if refusal:
        return refusal + "\n\n" + reclaim_report()
    if started_with is not None and started_with < DISK_FLOOR:
        print("  {} is set, so the {} floor was not enforced".format(
            LOW_DISK_ENV, gb(DISK_FLOOR)))
    if len(chosen) < args.sample:
        print("only {} of the {} requested meet the rule\n".format(
            len(chosen), args.sample))

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, DIFFERENTIAL_NAME)
    refuse_overwrite(out_path, DIFFERENTIAL_NAME)
    records, interruption = execute(chosen, timeout=args.timeout,
                                    arch=args.arch, runner=runner)
    ended_with, read_from_end, limitation_end = disk_headroom()
    summarise(records, interruption=interruption)
    print("\ncontainer daemon growth headroom: {} at the start, {} now"
          .format(gb(started_with), gb(ended_with)))
    print("  " + HEADROOM_LIMITATION)
    write(out_path, records, selection, {
        "runner": "{} ({})".format(version_text, runner),
        "runner_version": ".".join(str(n) for n in version),
        "timeout_seconds": args.timeout,
        "architecture": args.arch,
        "secrets_supplied": "none, by construction: no secret file is read, "
                            "no secret is passed, credential-shaped variables "
                            "are removed from the runner's environment",
        "disk": {
            "$comment": DISK_COMMENT,
            "floor": gb(DISK_FLOOR),
            "floor_bytes": DISK_FLOOR,
            "floor_enforced": not low_disk_allowed(),
            "headroom_at_start": gb(started_with),
            "headroom_at_start_bytes": started_with,
            "headroom_at_end": gb(ended_with),
            "headroom_at_end_bytes": ended_with,
            "read_from": read_from,
            "read_from_at_end": read_from_end,
            "headroom_limitation": HEADROOM_LIMITATION,
            "limitation": limitation,
            "limitation_at_end": limitation_end,
            "stopped_early": interruption,
        },
    })
    print("\nwrote " + out_path)
    return 0


__all__ = ["ANSWERS", "DISK_FLOOR", "DOCKER_READ_ONLY", "OUTCOMES",
           "PROVES_NOTHING", "RUNNER_MIN",
           "SELECTION_RULE", "aggregate", "assert_no_secret",
           "build_parser", "classify_outcome", "disk_headroom", "docker_read",
           "execute", "find_runner", "gb", "low_disk_allowed",
           "main", "plan",
           "read_steps", "reclaim_report", "reclaimable", "require_disk",
           "require_sample", "runner_argv", "runner_version",
           "scrubbed_env", "select", "summarise", "write"]

if __name__ == "__main__":
    sys.exit(main())
