#!/usr/bin/env python3
"""The differential-execution harness, entirely offline.

Nothing here starts a container, clones anything or reaches the network. What
is checked is the part that can be wrong without anybody noticing: the guards,
and the direction the log reading is wrong in.

The guards first, because this is the one module in the repository that
executes third-party code, and a guard that stopped holding would not show up
in any output.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.harness import offline, run                      # noqa: E402

offline()

from ciprofile import differential as D                      # noqa: E402
from ciprofile import report                                 # noqa: E402


# ---------------------------------------------------------------- the guards


def sample_size_is_required():
    """No default sample size, in any spelling.

    The accident this stops is the worst one available here: a command that
    looked like a query and started executing a corpus of third-party build
    scripts. Zero and None are both "not given", because argparse hands back
    None and a shell hands back 0.
    """
    for missing in (None, 0):
        refusal = D.require_sample(missing)
        assert refusal, "a sample size of {!r} was accepted".format(missing)
        assert "no default" in refusal, refusal
    assert D.require_sample(1) is None
    assert D.require_sample(D.SAMPLE_CEILING) is None


def a_sample_above_the_ceiling_is_refused():
    """The typo, and the escape hatch for the decision.

    Refused with the ceiling named, and overridable only in writing. The
    override is passed in here rather than set in the environment, so the
    check cannot be made to pass by whatever the environment happens to hold.
    """
    refusal = D.require_sample(D.SAMPLE_CEILING + 1, allow_large=False)
    assert refusal, "a sample above the ceiling was accepted"
    assert str(D.SAMPLE_CEILING) in refusal, refusal
    assert D.LARGE_SAMPLE_ENV in refusal, refusal
    assert D.require_sample(D.SAMPLE_CEILING + 1, allow_large=True) is None
    assert D.require_sample(10 ** 6, allow_large=True) is None


def the_runner_is_never_given_a_secret():
    """No secret path reaches the runner, and the default one is closed off.

    Two separate properties, and the second is the one that is easy to lose.
    The runner's DEFAULT secret file is `.secrets` in its working directory,
    and that directory is a clone of somebody else's repository, so omitting
    the flag would let a file inside the corpus feed secrets to the experiment
    that is meant to have none.
    """
    argv = D.runner_argv("/clone", "/clone/.github/workflows/ci.yml")
    assert "--secret-file" in argv, argv
    assert argv[argv.index("--secret-file") + 1] == os.devnull, argv
    assert "--env-file" in argv, argv
    assert argv[argv.index("--env-file") + 1] == os.devnull, argv
    for part in argv:
        assert part not in ("-s", "--secret"), part
        assert not part.startswith(("--secret=", "-s=")), part
    assert D.assert_no_secret(argv) is None


def a_secret_smuggled_into_the_command_is_refused():
    """The guard is a check on argv, not a comment on how argv is built.

    Every shape that would hand the runner a secret: the short flag, the long
    flag, a secret file that is not the null device, and the absence of the
    flag altogether.
    """
    good = D.runner_argv("/clone", "/clone/.github/workflows/ci.yml")
    for bad in (good + ["-s", "TOKEN=x"],
                good + ["--secret", "TOKEN=x"],
                good + ["--secret=TOKEN=x"]):
        assert D.assert_no_secret(bad), bad
    swapped = list(good)
    swapped[swapped.index("--secret-file") + 1] = "/tmp/.secrets"
    assert D.assert_no_secret(swapped), swapped
    assert D.assert_no_secret(good + ["--secret-file=/tmp/.secrets"])
    stripped = [p for i, p in enumerate(good)
                if p != "--secret-file"
                and good[i - 1] != "--secret-file"]
    assert D.assert_no_secret(stripped), stripped


def credential_shaped_variables_leave_the_environment():
    """What the runner's own process is handed, with DOCKER_* kept.

    Belt and braces rather than the mechanism, and checked anyway because its
    failure is silent: the mechanism is that no secret is passed at all.
    DOCKER_HOST has to survive or the runner cannot reach the daemon, and an
    image pull is not the workflow.
    """
    kept = D.scrubbed_env({
        "PATH": "/usr/bin", "HOME": "/home/x", "DOCKER_HOST": "unix:///x",
        "DOCKER_CONFIG": "/home/x/.docker", "LANG": "C"})
    assert sorted(kept) == ["DOCKER_CONFIG", "DOCKER_HOST", "HOME", "LANG",
                            "PATH"], sorted(kept)
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "FORGE_TOKEN", "NPM_TOKEN",
                 "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID", "SSH_AUTH_SOCK",
                 "MY_API_KEY", "DB_PASSWORD", "SONAR_TOKEN", "VAULT_ADDR",
                 "CODECOV_TOKEN", "REGISTRY_CREDENTIALS", "BASIC_AUTH"):
        out = D.scrubbed_env({"PATH": "/usr/bin", name: "x"})
        assert name not in out, name
        assert "PATH" in out, name


def the_output_filename_refuses_the_other_outputs():
    """The shared guard, reused rather than reimplemented.

    By basename, which is what lets this check aim at a scratch directory and
    still prove the property. A check that proved it by aiming a real write at
    a real corpus file destroyed one once; see EXPERIMENTS.md, "A destructive
    test".
    """
    scratch = tempfile.mkdtemp()
    assert D.DIFFERENTIAL_NAME in report.ALL_OUTPUT_NAMES
    for name in sorted(report.ALL_OUTPUT_NAMES - {D.DIFFERENTIAL_NAME}):
        try:
            D.write(os.path.join(scratch, name), [], {}, {})
        except SystemExit as e:
            assert "refusing to write" in str(e), str(e)
        else:
            raise AssertionError("wrote somebody else's output: " + name)
    assert os.listdir(scratch) == [], os.listdir(scratch)
    D.write(os.path.join(scratch, D.DIFFERENTIAL_NAME), [], {}, {})
    assert os.listdir(scratch) == [D.DIFFERENTIAL_NAME]


def a_runner_too_old_to_run_the_corpus_is_refused():
    """The version floor, which is a measurement input and not an install note.

    A runner below the floor refuses every action built on a Node runtime
    newer than node16, so a corpus measured with one reports an environment
    failure for nearly every repository in it. That distribution is not a
    finding and must not be producible, so the floor refuses rather than
    warns.
    """
    versions = {"/old/bin/act": "act version 0.2.33",
                "/new/bin/act": "act version 0.2.89"}

    def ask(path):
        return versions.get(path, "")

    path, _v, reason = D.find_runner("/old/bin", ask=ask)
    assert path is None, path
    assert "0.2.33" in reason and "node16" in reason, reason
    path, version, text = D.find_runner("/new/bin", ask=ask)
    assert path == "/new/bin/act", path
    assert version == (0, 2, 89), version
    assert "0.2.89" in text, text
    path, _v, reason = D.find_runner("", ask=ask)
    assert path is None and "on PATH" in reason, reason


def the_newest_runner_on_the_path_wins_not_the_first():
    """Otherwise the PATH order decides what the measurement says.

    A host carrying two installs resolves to whichever directory comes first,
    and on the host this was written against the first one was the one below
    the floor. Both orders have to give the same answer.
    """
    versions = {"/old/bin/act": "act version 0.2.33",
                "/new/bin/act": "act version 0.2.89"}

    def ask(path):
        return versions.get(path, "")

    for order in ("/old/bin" + os.pathsep + "/new/bin",
                  "/new/bin" + os.pathsep + "/old/bin"):
        path, version, _t = D.find_runner(order, ask=ask)
        assert path == "/new/bin/act", (order, path)
        assert version == (0, 2, 89), (order, version)
    assert D.runner_version("act version 0.2.89") == (0, 2, 89)
    assert D.runner_version("no version here") is None


def the_resolved_runner_is_what_runs():
    """The argv's first element is the resolved binary, not a bare name.

    Resolving the newest and then invoking whatever PATH finds would undo the
    resolution silently.
    """
    argv = D.runner_argv("/clone", "/clone/.github/workflows/ci.yml",
                         runner="/new/bin/act")
    assert argv[0] == "/new/bin/act", argv
    assert D.assert_no_secret(argv) is None


def a_budget_that_runs_out_takes_the_whole_session_with_it():
    """The runner's children die with it, including the one holding a container.

    Signalling only the runner leaves its teardown children, and the container
    they manage, running. That container then consumes the host while the NEXT
    repository runs, so one timeout would quietly measure every repository
    after it under contention: a defect that moves figures and shows up
    nowhere in the output.

    Proved on a process that outlives a cooperative stop and on its
    grandchild, which is the thing a per-process signal would miss.
    """
    proc = subprocess.Popen(
        ["/bin/sh", "-c", 'trap "" TERM; sleep 30 & echo $!; wait'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True)
    for _ in range(100):                  # the grandchild's pid, once printed
        line = proc.stdout.readline()
        if line.strip():
            break
    grandchild = int(line.strip())
    os.kill(grandchild, 0)                # alive, and ignoring TERM
    assert D.STOP_GRACE > 1, "the real grace period; this check sets its own"
    D._stop_session(proc, grace=1, log=lambda _m: None)
    assert proc.poll() is not None, "the runner itself survived"
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        os.kill(grandchild, 9)
        raise AssertionError("the grandchild survived the stop")


def run_workflow_stops_the_session_when_the_budget_runs_out():
    """The timeout path through run_workflow itself, not just its helper.

    Checking the helper alone left the call site untested: a run_workflow that
    went back to killing the runner outright passed every check while leaving
    containers behind. So this drives the real function with a stand-in runner
    that spawns a child, and asserts on the child.
    """
    scratch = tempfile.mkdtemp()
    pidfile = os.path.join(scratch, "child.pid")
    fake = os.path.join(scratch, "act")
    with open(fake, "w") as fh:
        fh.write("#!/bin/sh\nsleep 60 &\necho $! > {}\nsleep 60\n"
                 .format(pidfile))
    os.chmod(fake, 0o755)
    outcome, _reason, _ev, seconds, _log = D.run_workflow(
        scratch, os.path.join(scratch, "ci.yml"), 1, runner=fake,
        log=lambda _m: None)
    assert outcome == D.TIMED_OUT, outcome
    assert outcome in D.PROVES_NOTHING
    assert seconds < 30, seconds
    child = int(open(pidfile).read().strip())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        raise AssertionError("the stand-in runner's child survived")


# The scenario the check below needs, run in a process of its own because it
# is the one scenario that can kill the process running it. A session of its
# own first, so that whatever gets signalled is this child's group and never
# the test suite's; then a stand-in runner deliberately left in that same
# group, which is the condition the guard exists for; then the word that says
# this process is still here to say it.
OWN_GROUP_SCENARIO = """
import os, subprocess, sys
os.setsid()
sys.path.insert(0, %r)
from ciprofile import differential as D
proc = subprocess.Popen(["/bin/sh", "-c", "sleep 60"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
assert os.getpgid(proc.pid) == os.getpgrp(), "the scenario did not share"
said = []
D._stop_session(proc, grace=2, log=said.append)
assert proc.poll() is not None, "the stand-in runner survived"
assert any("session of its own" in m for m in said), said
print("survived")
"""


def stopping_never_signals_the_group_it_is_running_in():
    """The guard that makes the mutation above survivable at all.

    A group signal is only ever correct because the runner is started in a
    session of its own. If it ever is not, the group is this process's group
    and the SIGKILL takes the whole run down with it, results included. That
    is measured rather than imagined: a mutation test that removed
    `start_new_session` killed its own harness, twice, before the guard
    existed.

    Which is also why the scenario runs in a child. A check cannot report a
    failure from inside a process it has just killed, so asserting this
    in-process would have made the mutation that breaks the guard
    indistinguishable from a crash. The child says "survived" or it does not,
    and this process is always there to read the answer. See CONTRIBUTING.md:
    a test that can destroy its own run is a bug in the test.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-c", OWN_GROUP_SCENARIO % root],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    out = proc.stdout.decode("utf-8", "replace")
    assert "survived" in out, out[-600:]


def the_runner_runs_outside_the_clone():
    """The clone is the runner's target, never its working directory.

    The runner reads a `.actrc` out of its working directory, so invoking it
    inside a clone of somebody else's repository would let a file in the
    corpus add flags to the command measuring it. The clone therefore arrives
    as `-C`, and the working directory is set elsewhere by run_workflow().
    """
    argv = D.runner_argv("/clone", "/clone/.github/workflows/ci.yml")
    assert argv[argv.index("-C") + 1] == "/clone", argv
    assert "-W" in argv and argv[argv.index("-W") + 1].startswith("/clone/")
    assert "--container-architecture" in argv, argv


# ---------------------------------------------------------------- the disk
#
# Entirely offline, like everything else here: no daemon is asked anything, no
# container is started, and nothing on the machine's disk is created or removed
# beyond a scratch directory and a sparse file standing in for a VM image.


def about(got, want, slack=10 ** 9):
    """Two readings of the same disk, taken a moment apart.

    Free space on a working machine moves between two calls, so a check that
    demanded equality would fail for reasons that have nothing to do with the
    property. A gigabyte of slack is far tighter than the distinctions these
    checks turn on, which are whole disks apart.
    """
    return got is not None and abs(got - want) < slack


def the_disk_preflight_refuses_below_the_floor():
    """A long run is not started on a disk that cannot hold it.

    The appetite being guarded against is not this harness's own: the tooling
    is 3.2 GB of runner image and toolcache, measured. It is the machine the
    run lands on, which owes this tool nothing and may be carrying tens of
    gigabytes of somebody else's images, volumes and build cache. The failure
    the floor prevents is a multi-hour run dying at repository six with no
    results, or a full disk breaking work that has nothing to do with it.

    The message has to carry the floor, what was found and the difference,
    because "not enough space" sends the operator off to measure what this
    function has already measured. And it has to carry the limitation, because
    the figure it refuses on is growth headroom: the floor guards the host
    filling up, and passing it is not a statement that the daemon has room
    inside its own filesystem.
    """
    found = D.DISK_FLOOR - 3 * 1000 ** 3
    refusal = D.require_disk(found, allow_low=False)
    assert refusal, "a run was allowed to start on a disk below the floor"
    assert D.gb(found) in refusal, refusal
    assert D.gb(D.DISK_FLOOR) in refusal, refusal
    assert D.gb(D.DISK_FLOOR - found) in refusal, refusal   # how much to free
    assert D.LOW_DISK_ENV in refusal, refusal
    assert "growth headroom" in refusal, refusal
    assert D.HEADROOM_LIMITATION in refusal, refusal
    assert D.require_disk(D.DISK_FLOOR, allow_low=False) is None
    assert D.require_disk(D.DISK_FLOOR + 1, allow_low=False) is None
    # A floor at or below the footprint of the tooling would refuse nothing
    # that mattered: it has to leave room for a repository as well.
    assert D.DISK_FLOOR > 4 * 1000 ** 3, D.DISK_FLOOR
    # And an unreadable figure is not a refusal. There is nothing to refuse
    # on, and disk_headroom() has already said so in its limitation.
    assert D.require_disk(None, allow_low=False) is None


def the_low_disk_escape_hatch_overrides_the_floor():
    """The floor stops an accident, not a decision.

    The same shape as the sample ceiling's hatch: overridable, in writing, in
    the environment, and named in the refusal so the operator does not have to
    find it in a document. Passed in here rather than read from the
    environment, so whatever this machine happens to hold cannot decide the
    answer.
    """
    tight = D.DISK_FLOOR // 100
    assert D.require_disk(tight, allow_low=False), "the floor did not hold"
    assert D.require_disk(tight, allow_low=True) is None
    assert D.require_disk(0, allow_low=True) is None
    for said, allowed in (("", False), ("0", False), ("1", True),
                          ("yes", True)):
        assert D.low_disk_allowed({D.LOW_DISK_ENV: said}) is allowed, said
    assert D.low_disk_allowed({}) is False


def a_shortfall_between_repositories_stops_the_run_with_its_results():
    """A run that stops early with its results intact beats one that dies.

    The preflight measured a machine that was not then running containers, so
    the figure in front of the NEXT repository is a different figure. When it
    is below the floor the loop breaks and the records so far are returned and
    written: four answered repositories is a result, and a run killed by a
    full disk at repository five is not.

    Driven through the real execute() with the clone and the runner injected,
    for the same reason find_runner takes `ask`: a check that had to fill a
    disk and start a container to exercise this is a check nobody runs.
    """
    chosen = [{"repo": name, "owner": name.split("/")[0],
               "workflows": [".github/workflows/ci.yml"],
               "unresolved": ["credentials-unclear"],
               "test_invocation_recognised": True}
              for name in ("a/one", "b/two", "c/three")]
    ran = []

    def clone_fn(repo, into, log=print):
        ran.append(repo)
        return True

    def run_fn(clone_dir, workflow, budget, arch=None, runner=None,
               log=print):
        return D.RAN_UNPRIVILEGED, "every step ran", "", 1.0, ""

    records, interruption = D.execute(
        chosen, pace=0, log=lambda _m: None, clone_fn=clone_fn, run_fn=run_fn,
        space=lambda: D.DISK_FLOOR // 4, allow_low=False)
    assert [r["repo"] for r in records] == ["a/one"], records
    assert ran == ["a/one"], ran                 # nothing further was cloned
    assert records[0]["outcome"] == D.RAN_UNPRIVILEGED, records[0]
    assert interruption, "the run carried on below the floor"
    assert interruption["stopped_before"] == "b/two", interruption
    assert interruption["completed"] == 1, interruption
    assert interruption["selected"] == 3, interruption
    assert D.LOW_DISK_ENV in interruption["reason"], interruption
    # The stop records the figure it stopped on under the name of what that
    # figure is, so a reader does not take it for the daemon's free space.
    assert interruption["headroom_bytes"] == D.DISK_FLOOR // 4, interruption
    assert interruption["headroom"] == D.gb(D.DISK_FLOOR // 4), interruption
    # The partial results are written, with the stop on the record, so a
    # reader does not meet a one-repository distribution and take it for the
    # sample that was asked for.
    scratch = tempfile.mkdtemp()
    path = D.write(os.path.join(scratch, D.DIFFERENTIAL_NAME), records, {},
                   {"disk": {"stopped_early": interruption}})
    out = json.loads(open(path).read())
    assert out["outcomes"][D.RAN_UNPRIVILEGED] == 1, out["outcomes"]
    assert len(out["repositories"]) == 1, out["repositories"]
    assert out["disk"]["stopped_early"]["stopped_before"] == "b/two", out
    said = []
    D.summarise(records, log=said.append, interruption=interruption)
    assert any("PARTIAL" in m for m in said), said
    # And a run with room runs to the end, reporting no interruption at all.
    records, interruption = D.execute(
        chosen, pace=0, log=lambda _m: None, clone_fn=clone_fn, run_fn=run_fn,
        space=lambda: D.DISK_FLOOR * 10, allow_low=False)
    assert [r["repo"] for r in records] == ["a/one", "b/two", "c/three"]
    assert interruption is None, interruption
    said = []
    D.summarise(records, log=said.append, interruption=None)
    assert not any("PARTIAL" in m for m in said), said


def the_daemons_own_figure_is_preferred_to_the_hosts():
    """The host filesystem answers a different question, and answers it kindly.

    What fills during a run is the disk the daemon writes images, volumes and
    container layers to. On macOS that disk is inside a VM, so a host with
    room to spare says nothing about whether the next image pull fits, and a
    preflight that read the host would wave through exactly the run it exists
    to stop.

    Both daemon readings are exercised. Proving the preference by comparing
    two numbers would be vacuous, because a machine's docker root and its
    scratch space are usually the same filesystem; so the host read is made to
    FAIL instead, and a figure coming back at all can only have come from the
    daemon's own directory.

    What the VM reading measures is growth headroom and not the free space
    inside the VM, and its limitation has to say so: a daemon that is
    internally full while the host still has room passes this preflight.
    """
    root = tempfile.mkdtemp()
    headroom, how, limitation = D.disk_headroom(
        scratch=os.path.join(root, "nonexistent"),
        run=lambda argv: (root + "\n", ""))
    assert headroom and headroom > 0, headroom
    assert root in how and "storage directory" in how, how
    assert limitation == "", limitation
    # The VM reading, for the host where the daemon's root is inside a VM and
    # so is not on this filesystem at all. A sparse file stands in for the
    # image: its unwritten remainder is the headroom.
    image = os.path.join(root, "Docker.raw")
    with open(image, "wb") as fh:
        fh.truncate(4096)
    headroom, how, limitation = D.disk_headroom(
        scratch=root, run=lambda argv: ("/var/lib/docker-absent\n", ""),
        images=(image,))
    assert headroom == 4096, headroom
    assert image in how, how
    # The claim the limitation must make, and the one it must not: it is how
    # much further the image could grow, never how much room is left in it.
    assert "HOW MUCH FURTHER" in limitation, limitation
    assert "inside its own" in limitation, limitation
    assert "LOWER BOUND" not in limitation, limitation
    # And the VM figure is capped by the host it grows into, or a disk image
    # declared larger than the machine would read as room the machine has not
    # got.
    with open(image, "wb") as fh:
        fh.truncate(10 ** 15)
    headroom, _how, _limitation = D.disk_headroom(
        scratch=root, run=lambda argv: ("/var/lib/docker-absent\n", ""),
        images=(image,))
    assert about(headroom, shutil.disk_usage(root).free), headroom
    # The caveat on the whole figure, published with every reading: this guard
    # is against filling the host and names the symptom of the case it cannot
    # see, which is a run that fails on a write after the preflight passed.
    assert "FILLING THE HOST" in D.HEADROOM_LIMITATION
    assert "internally full" in D.HEADROOM_LIMITATION
    assert "fails on a write" in D.HEADROOM_LIMITATION


def an_unreadable_daemon_figure_falls_back_and_records_the_limitation():
    """A substitute figure is reported as a substitute, never passed off.

    There is no vendor-neutral way to ask a daemon in a VM how much room it
    has left, so the host figure is sometimes the only one there is. Reporting
    it silently would put a number in the output that reads as the daemon's
    and can be generous by any amount, which is the same error as reading a
    log line nothing matched as evidence.
    """
    scratch = tempfile.mkdtemp()
    host = shutil.disk_usage(scratch).free
    headroom, how, limitation = D.disk_headroom(
        scratch=scratch, run=lambda argv: (None, "`docker` did not run"),
        images=())
    assert about(headroom, host), (headroom, host)
    assert scratch in how and "host filesystem" in how, how
    assert "COULD NOT BE READ" in limitation, limitation
    assert "did not run" in limitation, limitation
    # The daemon answered, but with a root directory that is somewhere else.
    # Same substitution, and it still says which.
    headroom, how, limitation = D.disk_headroom(
        scratch=scratch, run=lambda argv: ("/var/lib/docker-absent\n", ""),
        images=())
    assert about(headroom, host), (headroom, host)
    assert "/var/lib/docker-absent" in limitation, limitation
    assert "not on this filesystem" in limitation, limitation
    # And when neither can be read there is no figure to refuse on, which is
    # said rather than guessed at in either direction.
    headroom, _how, limitation = D.disk_headroom(
        scratch=os.path.join(scratch, "nonexistent"),
        run=lambda argv: (None, "no daemon"), images=())
    assert headroom is None, headroom
    assert "NEITHER THE DAEMON NOR THE HOST" in limitation, limitation
    assert D.require_disk(headroom, allow_low=False) is None
    assert D.gb(None) == "unknown"


# The commands a disk check could be tempted into. Matched on word boundaries
# rather than as bare substrings, because `rmi` sits inside `determination` and
# a check that fired on that would be deleted rather than fixed. The advice
# constant is allowed to name these, because it is printed for the operator to
# act on; nothing else in the module may.
PRUNING = (r"\bprune", r"\brmi\b", r"docker\s+rm\b", r"image\s+rm\b",
           r"volume\s+rm\b", r"container\s+rm\b", r"network\s+rm\b",
           r"--volumes\b")
EXECUTING = ("subprocess.run", "subprocess.popen", "subprocess.call",
             "subprocess.check_output", "os.system", "os.popen", "os.execv",
             "os.spawnv")


def dotted(node):
    """`subprocess.run` out of a Call's func, spelled as it is written."""
    bits = []
    while isinstance(node, ast.Attribute):
        bits.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        bits.append(node.id)
    return ".".join(reversed(bits))


def nothing_here_prunes_anything():
    """The operator's images, volumes and build cache are not this tool's.

    A measurement instrument that freed somebody's disk to make room for its
    own run would have destroyed data nobody asked it to touch, and a full
    disk is much the cheaper of the two failures. So the help offered is a
    figure and a command, and the decision stays with whoever owns the
    machine.

    Asserted from the source, the way the adapters' read-only property is: one
    `docker volume prune` is all it would take, and it would not show up in
    any output. Three ways, because each would miss the others. The allowlist
    is the mechanism; the source scan catches a command built around it; and
    the recorded argv proves what the preflight actually issues.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "ciprofile", "differential.py")).read()
    tree = ast.parse(src)

    # Every string the module holds, except the advice constant's own, is
    # checked for a destructive command. The advice is carved out by identity
    # rather than by rewriting the text, so a second constant that started
    # naming one would not slip through with it.
    advice = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "RECLAIM_ADVICE"
                for t in node.targets):
            advice |= {id(n) for n in ast.walk(node)}
    assert advice, "RECLAIM_ADVICE is no longer a module-level assignment"
    # Docstrings are prose and cannot run, and this module explains at length
    # what it will not do, so it names the commands it refuses to issue. What
    # is scanned is every string that is not one: the place a command would
    # have to be written to reach a daemon.
    spared = set(advice)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) \
                    and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                spared.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in spared:
            said = node.value.lower()
            for verb in PRUNING:
                assert not re.search(verb, said), (verb, node.value[:120])

    # And the advice is advice: it is never handed to anything that runs.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and dotted(node.func).lower() in EXECUTING:
            for inner in ast.walk(node):
                assert not (isinstance(inner, ast.Name)
                            and inner.id == "RECLAIM_ADVICE"), \
                    dotted(node.func)

    # The allowlist, which is where "it only ever reads" is enforced rather
    # than hoped for.
    assert D.DOCKER_READ_ONLY, "the allowlist is empty"
    for words in D.DOCKER_READ_ONLY.values():
        assert words[0] in ("info", "system"), words
        # `run`, `exec` and `start` sit here with the destructive verbs for a
        # second property: the disk reading measures growth headroom and not
        # the daemon's internal free space, and the better figure is one
        # container launch away. This is where "no container is started to
        # improve a number" is enforced rather than promised in a docstring.
        for verb in ("prune", "rm", "rmi", "create", "build", "load",
                     "import", "kill", "stop", "run", "exec", "start"):
            assert verb not in words, (words, verb)
    assert D.DOCKER_READ_ONLY["usage"][:2] == ("system", "df"), \
        D.DOCKER_READ_ONLY["usage"]
    # A command absent from it is refused before anything is spawned, which is
    # why asking for one costs no daemon call here.
    for wanted in ("prune", "image prune", "volume rm", ""):
        text, reason = D.docker_read(wanted)
        assert text == "", (wanted, text)
        assert "not a read-only docker command" in reason, (wanted, reason)

    # Every argv the whole preflight issues, recorded. The source scan says
    # the words are absent; this says what is actually run.
    seen = []

    def run(argv):
        seen.append(list(argv))
        return "", "no daemon on this machine"

    D.disk_headroom(run=run, images=())
    D.reclaim_report(run=run)
    assert seen, "the preflight asked the daemon nothing at all"
    allowed = {tuple(v) for v in D.DOCKER_READ_ONLY.values()}
    for argv in seen:
        assert argv[0] == D.DOCKER, argv
        assert tuple(argv[1:]) in allowed, argv
    # The report quotes the daemon's figures and names the commands, and that
    # is the whole of the help it offers.
    said = D.reclaim_report(run=lambda argv: (
        '{"Type":"Images","Size":"60.35GB","Reclaimable":"37.77GB (62%)"}\n'
        '{"Type":"Build Cache","Size":"47.33GB","Reclaimable":"20.8GB"}\n',
        ""))
    assert "60.35GB" in said and "37.77GB" in said, said
    assert "Build Cache" in said, said
    assert "yours to decide" in said, said
    assert D.reclaim_report(run=lambda argv: ("", "nothing")) \
        == D.RECLAIM_ADVICE


# ------------------------------------------------- what a failure may be read as


GREEN = """\
[CI/build] \u2b50 Run Main actions/checkout@v4
[CI/build]   \u2705  Success - Main actions/checkout@v4
[CI/build] \u2b50 Run Main npm ci
added 420 packages
[CI/build]   \u2705  Success - Main npm ci
[CI/build] \u2b50 Run Main npm test
[CI/build]   \u2705  Success - Main npm test
[CI/build] \U0001f3c1  Job succeeded
"""

# Lines copied from a real run, abridged in the middle and nowhere else. The
# three details that break a reading built from the documentation rather than
# from the output are all here: the duration suffix on the result line, the
# optional Pre and Post phases, and the job envelope's own phaseless entries.
REAL = """\
[Build/build] \u2b50 Run Main actions/checkout@v4
[Build/build]   \u2705  Success - Main actions/checkout@v4
[Build/build] \u2b50 Run Main Use Node.js
[Build/build]   \U0001f6a7  ::warning::Failed to restore: connect EHOSTUNREACH
[Build/build]   \u2705  Success - Main Use Node.js  [23.455690375s]
[Build/build] \u2b50 Run Main npm ci
[Build/build]   | added 1080 packages
[Build/build]   \u2705  Success - Main npm ci [1m1.861640125s]
[Build/build] \u2b50 Run Main npm run build
[Build/build]   | Application bundle generation complete. [13.138 seconds]
[Build/build]   \u2705  Success - Main npm run build [15.670510708s]
[Build/build] \u2b50 Run Post Use Node.js
[Build/build]   \U0001f6a7  ::warning::Failed to save: reserveCache failed: \
connect EHOSTUNREACH 192.168.1.32:57710
[Build/build]   \u2705  Success - Post Use Node.js  [17.39722975s]
[Build/build] \u2b50 Run Complete job
[Build/build] Cleaning up container for job build
[Build/build]   \u2705  Success - Complete job
[Build/build] \U0001f3c1  Job succeeded
"""


def the_real_log_format_is_what_is_parsed():
    """Against lines from an actual run, not from the documentation.

    Each of these cost a reading when it was missed. The duration suffix on
    the result line is the worst: pair steps by name without stripping it and
    NOTHING is ever paired, so every run looks like one where no step
    finished and the whole corpus reads as an environment failure. A green
    distribution turning into an all-environment-failure one is exactly the
    kind of defect that looks like a finding.
    """
    steps = D.read_steps(REAL)
    names = [(s["phase"], s["name"], s["result"]) for s in steps]
    assert ("Main", "npm ci", "Success") in names, names
    assert ("Main", "npm run build", "Success") in names, names
    assert ("Post", "Use Node.js", "Success") in names, names
    assert (None, "Complete job", "Success") in names, names
    assert all(s["result"] is not None for s in steps), names
    outcome, _r, _ev = D.classify_outcome(0, REAL)
    assert outcome == D.RAN_UNPRIVILEGED, outcome


def a_warning_in_a_step_that_succeeded_is_never_consulted():
    """The cache warnings a local runner always emits are not failures.

    A run with no cache service warns twice per workflow about an unreachable
    host, in steps that succeed. Reading the log as a whole would turn every
    green run in the corpus into an environment failure.
    """
    assert "EHOSTUNREACH" in REAL
    outcome, _r, evidence = D.classify_outcome(0, REAL)
    assert outcome == D.RAN_UNPRIVILEGED, outcome
    assert evidence == "", evidence


def a_failure_in_the_job_envelope_is_not_a_project_command():
    """The envelope's phaseless entries cannot produce the executed reading.

    `ran-with-failures` requires a Main-phase step, because a failure in the
    runner's own bookkeeping is the runner's and not the pipeline's.
    """
    log = ("[CI/build] \u2b50 Run Complete job\n"
           "BUILD FAILED somewhere in the bookkeeping\n"
           "[CI/build]   \u274c  Failure - Complete job\n")
    outcome, _r, _ev = D.classify_outcome(1, log)
    assert outcome == D.ENVIRONMENT_FAILURE, outcome


def a_clean_run_is_the_positive_case():
    """Exit zero with no failing step, and no pattern table consulted.

    This is the only class that rests on an absence rather than on a reading,
    which is why it is the only one quotable on its own.
    """
    outcome, reason, _ev = D.classify_outcome(0, GREEN)
    assert outcome == D.RAN_UNPRIVILEGED, (outcome, reason)
    assert outcome in D.ANSWERS
    steps = D.read_steps(GREEN)
    assert [s["name"] for s in steps] == ["actions/checkout@v4", "npm ci",
                                          "npm test"], steps
    assert all(s["result"] == "Success" for s in steps), steps


def a_missing_secret_is_read_as_needing_one():
    """The one reading that carries a positive privilege claim.

    Only where the failing step's own output says so. The wordings here are
    the shapes a pipeline with no secret actually fails in: an action input
    that was required, a registry rejecting the request, and a script saying
    the variable is empty.
    """
    for said in ("Error: Input required and not supplied: token",
                 "npm error code E401",
                 "npm error 401 Unauthorized - GET https://registry/x",
                 "fatal: Authentication failed for 'https://host/x'",
                 "Error: SONAR_TOKEN is not set",
                 "remote: Permission denied (publickey).",
                 "unauthorized: authentication required",
                 "Error: Credentials could not be loaded",
                 "aws: error: Unable to locate credentials"):
        log = ("[CI/build] \u2b50 Run Main publish\n"
               + said + "\n"
               + "[CI/build]   \u274c  Failure - Main publish\n")
        outcome, _r, ev = D.classify_outcome(1, log)
        assert outcome == D.SECRET_REQUIRED, (said, outcome)
        assert ev.strip() in said, (said, ev)


def a_credential_warning_elsewhere_does_not_convict():
    """The table is matched against the FAILING step's output and nothing else.

    Matching the whole log was the obvious first shape and it is wrong: a
    cache or registry warning from an earlier step reads as the failing step's
    own missing token, and `secret-required` is the reading that must not be
    given away.
    """
    log = ("[CI/build] \u2b50 Run Main actions/cache@v4\n"
           "Warning: Cache service responded with 401 Unauthorized\n"
           "[CI/build]   \u2705  Success - Main actions/cache@v4\n"
           "[CI/build] \u2b50 Run Main pytest\n"
           "E   AssertionError: assert 1 == 2\n"
           "1 failed, 3 passed\n"
           "[CI/build]   \u274c  Failure - Main pytest\n")
    outcome, _r, _ev = D.classify_outcome(1, log)
    assert outcome == D.RAN_WITH_FAILURES, outcome


def a_runner_limitation_outranks_the_credential_table():
    """Order, and the overlap that makes it load-bearing.

    The local runner fetches actions from a public API unauthenticated, so its
    own rate-limit rejection reads exactly like a project's missing token if
    the credential table is asked first. The runner's inability therefore
    comes first, and the reading falls to the class that claims nothing.
    """
    log = ("[CI/build] \u2b50 Run Main some/action@v1\n"
           "Error: Unable to resolve action some/action@v1, "
           "API rate limit exceeded: 403 Forbidden\n"
           "[CI/build]   \u274c  Failure - Main some/action@v1\n")
    outcome, _r, _ev = D.classify_outcome(1, log)
    assert outcome == D.ENVIRONMENT_FAILURE, outcome
    assert outcome in D.PROVES_NOTHING


def an_unrecognised_failure_claims_nothing():
    """The default, which is the asymmetry this module turns on.

    A failure nothing matches is neither evidence of a privilege nor evidence
    of its absence, so it lands in a class excluded from every share. Reverse
    this and every unreadable failure quietly becomes a reading.
    """
    log = ("[CI/build] \u2b50 Run Main ./build.sh\n"
           "wibble: frobnicating the grommet\n"
           "exit status 3\n"
           "[CI/build]   \u274c  Failure - Main ./build.sh\n")
    outcome, _r, _ev = D.classify_outcome(1, log)
    assert outcome == D.ENVIRONMENT_FAILURE, outcome
    assert outcome not in D.ANSWERS


def a_merit_signature_in_an_action_is_not_a_project_command():
    """`ran-with-failures` requires the project's own command to have run.

    A merit-looking string in an action's output would otherwise hand out the
    "it executed" reading, which is the flattering direction, on the strength
    of text the project did not produce.
    """
    log = ("[CI/build] \u2b50 Run Main codecov/codecov-action@v5\n"
           "AssertionError: internal\n"
           "[CI/build]   \u274c  Failure - Main codecov/codecov-action@v5\n")
    outcome, _r, _ev = D.classify_outcome(1, log)
    assert outcome == D.ENVIRONMENT_FAILURE, outcome


def a_test_failure_still_answers_the_question():
    """A suite that ran and failed answers the privilege question.

    The pipeline reached the project's own code with nothing granted, so
    nothing granted was blocking it. Reading this as a failure would make the
    instrument a measurement of whether other people's tests pass.
    """
    for said in ("FAILURE: Build failed with an exception.",
                 "Tests run: 12, Failures: 1, Errors: 0",
                 "--- FAIL: TestThing (0.00s)",
                 "E   AssertionError: assert 1 == 2",
                 "src/x.ts(3,1): error TS2322: Type 'string'",
                 "would reformat src/x.py",
                 "Execution failed for task ':test'."):
        log = ("[CI/build] \u2b50 Run Main run the suite\n" + said + "\n"
               "[CI/build]   \u274c  Failure - Main run the suite\n")
        outcome, _r, _ev = D.classify_outcome(1, log)
        assert outcome == D.RAN_WITH_FAILURES, (said, outcome)
        assert outcome in D.ANSWERS, said


def a_timeout_and_a_dead_runner_claim_nothing():
    outcome, _r, _ev = D.classify_outcome(None, GREEN, timed_out=True)
    assert outcome == D.TIMED_OUT, outcome
    outcome, _r, _ev = D.classify_outcome(1, "no container could be created")
    assert outcome == D.ENVIRONMENT_FAILURE, outcome
    outcome, _r, _ev = D.classify_outcome(1, "", started=False)
    assert outcome == D.NOT_ATTEMPTED, outcome
    assert set(D.PROVES_NOTHING).isdisjoint(D.ANSWERS)


def aggregation_lets_one_unreadable_file_hold_the_repository():
    """Strict, so a repository is not answered by its cheapest workflow.

    A secret-related failure outranks everything, so a privilege stays
    visible; and a file nothing could be concluded about outranks a clean one,
    because what a contributor has to run is every check their pull request
    sets off.
    """
    assert D.aggregate([D.RAN_UNPRIVILEGED]) == D.RAN_UNPRIVILEGED
    assert D.aggregate([D.RAN_UNPRIVILEGED,
                        D.SECRET_REQUIRED]) == D.SECRET_REQUIRED
    assert D.aggregate([D.RAN_UNPRIVILEGED,
                        D.ENVIRONMENT_FAILURE]) == D.ENVIRONMENT_FAILURE
    assert D.aggregate([D.RAN_UNPRIVILEGED,
                        D.RAN_WITH_FAILURES]) == D.RAN_WITH_FAILURES
    assert D.aggregate([]) == D.NOT_ATTEMPTED


# ------------------------------------------------------------- the selection


def _corpus():
    """A profile and a cache small enough to reason about."""
    def scope(primary, flags, signals, files):
        return {"primary": primary, "flags": flags, "signals": signals,
                "files": files}
    wf = ".github/workflows/ci.yml"
    clean = ("on:\n  pull_request:\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
             "    steps:\n      - run: npm test\n")
    profile = {"repos": {
        "a/unclear": {
            "pull_request": scope("read-credential", ["read-credential",
                                                      "credentials-unclear"],
                                  ["toolchain-node"], [wf]),
            "repository": scope("read-credential", ["read-credential"], [],
                                [wf])},
        "b/unidentified": {
            "pull_request": scope("self-contained",
                                  ["self-contained",
                                   "test-step-unidentified"],
                                  ["toolchain-python"], [wf]),
            "repository": scope("self-contained", ["self-contained"], [],
                                [wf])},
        "c/resolved": {
            "pull_request": scope("self-contained",
                                  ["self-contained",
                                   "credentials-reporting-only"],
                                  ["toolchain-node"], [wf]),
            "repository": scope("self-contained", ["self-contained"], [],
                                [wf])},
        "d/windows": {
            "pull_request": scope("self-contained",
                                  ["self-contained",
                                   "test-step-unidentified"],
                                  ["toolchain-node"], [wf]),
            "repository": scope("self-contained", ["self-contained"], [],
                                [wf])},
        "e/specialenv": {
            "pull_request": scope("special-env",
                                  ["special-env", "credentials-unclear"],
                                  ["toolchain-node"], [wf]),
            "repository": scope("special-env", ["special-env"], [], [wf])},
        "f/gitlab": {
            "pull_request": scope("self-contained",
                                  ["self-contained",
                                   "test-step-unidentified"],
                                  ["toolchain-node"], [".gitlab-ci.yml"]),
            "repository": scope("self-contained", ["self-contained"], [],
                                [".gitlab-ci.yml"])},
        "g/notoolchain": {
            "pull_request": scope("self-contained",
                                  ["self-contained",
                                   "test-step-unidentified"],
                                  [], [wf]),
            "repository": scope("self-contained", ["self-contained"], [],
                                [wf])},
        "a/zz-second": {
            "pull_request": scope("self-contained",
                                  ["self-contained",
                                   "test-step-unidentified"],
                                  ["toolchain-node"], [wf]),
            "repository": scope("self-contained", ["self-contained"], [],
                                [wf])},
        "h/nopipeline": {
            "pull_request": scope("no-pipeline", ["no-pipeline"], [], []),
            "repository": scope("no-pipeline", ["no-pipeline"], [], [])},
    }}
    cache = {"repos": {
        "a/unclear": {"files": {wf: clean}},
        "b/unidentified": {"files": {wf: clean}},
        "c/resolved": {"files": {wf: clean}},
        "d/windows": {"files": {wf: clean.replace("ubuntu-latest",
                                                  "windows-latest")}},
        "e/specialenv": {"files": {wf: clean}},
        "f/gitlab": {"files": {".gitlab-ci.yml": "test:\n  script: npm test\n"}},
        "g/notoolchain": {"files": {wf: clean}},
        "a/zz-second": {"files": {wf: clean}},
        "h/nopipeline": {"files": {}},
    }}
    return profile, cache


def selection_keeps_only_what_execution_can_decide():
    """Every rule in SELECTION_RULE takes out the case it names.

    One synthetic repository per rule, so a rule that stopped firing is a
    failure here rather than a sample that quietly drifted.
    """
    profile, cache = _corpus()
    chosen, rejected = D.select(profile, cache, 10)
    names = [r["repo"] for r in chosen]
    assert names == ["a/unclear", "b/unidentified"], names
    assert rejected["resolved by static reading"] == 1, rejected
    assert rejected["special-env"] == 1, rejected
    assert rejected["not entirely GitHub Actions"] == 1, rejected
    assert rejected[
        "asks for an environment the runner cannot provide"] == 1, rejected
    assert rejected["no recognised toolchain"] == 1, rejected
    assert rejected["a second repository from one owner"] == 1, rejected
    assert "h/nopipeline" not in names


def the_sample_size_is_honoured_and_the_order_is_fixed():
    profile, cache = _corpus()
    assert [r["repo"] for r in D.select(profile, cache, 1)[0]] == ["a/unclear"]
    assert D.select(profile, cache, 0)[0] == []
    first = D.select(profile, cache, 10)[0]
    second = D.select(profile, cache, 10)[0]
    assert [r["repo"] for r in first] == [r["repo"] for r in second]


def a_recognised_test_invocation_is_recorded_as_the_caveat():
    """What a clean run is evidence *about*.

    A workflow with no recognised test command that runs clean says something
    about the pull-request check and nothing about a test suite. The flag has
    to be on the record or the two readings collapse into each other.
    """
    profile, cache = _corpus()
    wf = ".github/workflows/ci.yml"
    cache["repos"]["b/unidentified"]["files"][wf] = (
        "on:\n  pull_request:\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: ./build.sh\n")
    chosen, _rejected = D.select(profile, cache, 10)
    by_name = {r["repo"]: r for r in chosen}
    assert by_name["a/unclear"]["test_invocation_recognised"] is True
    assert by_name["b/unidentified"]["test_invocation_recognised"] is False


def the_plan_is_printed_before_anything_runs():
    """What is about to execute, in the terminal, naming the command.

    A person about to have third-party build scripts run on their machine
    should be able to read the command rather than infer it.
    """
    profile, cache = _corpus()
    chosen, _rejected = D.select(profile, cache, 2)
    text = D.plan(chosen, D.TIMEOUT_DEFAULT, "linux/amd64")
    assert "NO SECRET SUPPLIED" in text, text
    assert "third-party code" in text, text
    assert "a/unclear" in text and "b/unidentified" in text, text
    assert "--secret-file " + os.devnull in text, text
    assert str(D.TIMEOUT_DEFAULT) in text, text


def the_timeout_is_defaulted_and_overridable():
    parsed = D.build_parser().parse_args(
        ["--profile", "p", "--cache", "c", "--sample", "3"])
    assert parsed.timeout == D.TIMEOUT_DEFAULT, parsed.timeout
    assert parsed.sample == 3
    parsed = D.build_parser().parse_args(
        ["--profile", "p", "--cache", "c", "--sample", "3",
         "--timeout", "60"])
    assert parsed.timeout == 60, parsed.timeout


def the_command_line_offers_no_way_to_pass_a_secret():
    """The absence is the experiment, so it is asserted and not assumed.

    Checked against the parser's own option strings rather than against the
    help text: a flag added later shows up here.
    """
    options = []
    for action in D.build_parser()._actions:
        options.extend(action.option_strings)
    for option in options:
        assert "secret" not in option.lower(), option
        assert "token" not in option.lower(), option
        assert "credential" not in option.lower(), option
    assert "--sample" in options and "--timeout" in options, options


def the_run_refuses_before_reading_anything_without_a_sample_size():
    """The refusal happens first, so a missing size cannot start work.

    `--dry-run` would also print a plan; the point is that the size is
    checked before the profile is even opened, so no spelling of the command
    gets as far as selecting.
    """
    out = D.main(["--profile", "/nonexistent", "--cache", "/nonexistent"])
    assert isinstance(out, str) and "no default" in out, out
    out = D.main(["--profile", "/nonexistent", "--cache", "/nonexistent",
                  "--sample", str(D.SAMPLE_CEILING + 1)])
    assert isinstance(out, str) and "ceiling" in out, out


if __name__ == "__main__":
    sys.exit(run([
        ("--sample is required, with no default",
         sample_size_is_required),
        ("a sample above the ceiling is refused, overridably",
         a_sample_above_the_ceiling_is_refused),
        ("the runner is never given a secret, default file included",
         the_runner_is_never_given_a_secret),
        ("a secret smuggled into the command line is refused",
         a_secret_smuggled_into_the_command_is_refused),
        ("credential-shaped variables leave the environment",
         credential_shaped_variables_leave_the_environment),
        ("the output filename refuses the other outputs",
         the_output_filename_refuses_the_other_outputs),
        ("a runner too old to run the corpus is refused",
         a_runner_too_old_to_run_the_corpus_is_refused),
        ("the newest runner on PATH wins, not the first",
         the_newest_runner_on_the_path_wins_not_the_first),
        ("the resolved runner is the one that runs",
         the_resolved_runner_is_what_runs),
        ("a budget that runs out takes the whole session with it",
         a_budget_that_runs_out_takes_the_whole_session_with_it),
        ("run_workflow stops the session when the budget runs out",
         run_workflow_stops_the_session_when_the_budget_runs_out),
        ("stopping never signals the group it is running in",
         stopping_never_signals_the_group_it_is_running_in),
        ("the runner runs outside the clone, so no .actrc is read from it",
         the_runner_runs_outside_the_clone),
        ("the disk preflight refuses below the floor",
         the_disk_preflight_refuses_below_the_floor),
        ("the low-disk escape hatch overrides the floor",
         the_low_disk_escape_hatch_overrides_the_floor),
        ("a shortfall between repositories stops the run with its results",
         a_shortfall_between_repositories_stops_the_run_with_its_results),
        ("the daemon's own figure is preferred to the host's",
         the_daemons_own_figure_is_preferred_to_the_hosts),
        ("an unreadable daemon figure falls back and records the limitation",
         an_unreadable_daemon_figure_falls_back_and_records_the_limitation),
        ("nothing here prunes anything, asserted from the source",
         nothing_here_prunes_anything),
        ("a clean run is the positive case and consults no pattern",
         a_clean_run_is_the_positive_case),
        ("the real log format is what is parsed, duration suffix included",
         the_real_log_format_is_what_is_parsed),
        ("a warning in a step that succeeded is never consulted",
         a_warning_in_a_step_that_succeeded_is_never_consulted),
        ("a failure in the job envelope is not a project command",
         a_failure_in_the_job_envelope_is_not_a_project_command),
        ("a missing or rejected credential is read as needing one",
         a_missing_secret_is_read_as_needing_one),
        ("a credential warning in another step does not convict",
         a_credential_warning_elsewhere_does_not_convict),
        ("the runner's own inability outranks the credential table",
         a_runner_limitation_outranks_the_credential_table),
        ("an unrecognised failure claims nothing",
         an_unrecognised_failure_claims_nothing),
        ("a merit signature in an action is not a project command",
         a_merit_signature_in_an_action_is_not_a_project_command),
        ("a test suite that ran and failed still answers the question",
         a_test_failure_still_answers_the_question),
        ("a timeout and a dead runner claim nothing",
         a_timeout_and_a_dead_runner_claim_nothing),
        ("one unreadable workflow file holds the repository unanswered",
         aggregation_lets_one_unreadable_file_hold_the_repository),
        ("selection keeps only what execution can decide",
         selection_keeps_only_what_execution_can_decide),
        ("the sample size is honoured and the order is fixed",
         the_sample_size_is_honoured_and_the_order_is_fixed),
        ("a recognised test invocation is recorded as the caveat",
         a_recognised_test_invocation_is_recorded_as_the_caveat),
        ("the plan is printed before anything runs",
         the_plan_is_printed_before_anything_runs),
        ("the per-repository timeout is defaulted and overridable",
         the_timeout_is_defaulted_and_overridable),
        ("the command line offers no way to pass a secret",
         the_command_line_offers_no_way_to_pass_a_secret),
        ("the run refuses before reading anything without a sample size",
         the_run_refuses_before_reading_anything_without_a_sample_size),
    ]))
