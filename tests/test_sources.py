#!/usr/bin/env python3
"""The four adapters: read-only, paced, and honest about emptiness.

The emptiness checks are the ones to keep. Three forges expose the question
differently and a wrong answer to it is invisible in the output: a repository
counted as doing no CI looks exactly like a repository that does no CI.
"""
import json
import os
import re
import sys
import tempfile

import harness
from harness import run

harness.offline()

from ciprofile import report, sources                            # noqa: E402
from ciprofile.classify import (NO_PIPELINE, PR_SCOPE,           # noqa: E402
                                REPO_SCOPE, classify)
from ciprofile.fixtures import FIXTURE_DIR, fixture_cases        # noqa: E402
from ciprofile.sources import base                               # noqa: E402
from ciprofile.sources.forgejo import ForgejoSource              # noqa: E402
from ciprofile.sources.github import GitHubSource                # noqa: E402
from ciprofile.sources.gitlab import GitLabSource                # noqa: E402
from ciprofile.sources.local import LocalSource                  # noqa: E402
from ciprofile.sweep import empty_verdict, fetch_repo, sweep     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(os.path.dirname(HERE), "ciprofile")
ADAPTERS = ["forgejo.py", "gitlab.py", "github.py", "local.py", "base.py"]


def read(name):
    with open(os.path.join(PKG, "sources", name)) as fh:
        return fh.read()


def read_only_by_construction():
    """The licence to point this at a platform somebody else operates, and to
    run it unattended. Asserted from the source rather than trusted: one
    `method=` argument is all it would take."""
    base_src = read("base.py")
    # One transport, and it cannot be told to use another verb: there is no
    # method parameter on it at all.
    assert "urllib.request.Request(url)" in base_src
    assert "def get(" in base_src
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in base_src, verb
    for name in [a for a in ADAPTERS if a != "base.py"]:
        src = read(name)
        # No adapter builds its own request, so none can smuggle a verb past
        # the shared transport.
        for bad in ("urllib.request", "urlopen", "put_file", "data=",
                    "method="):
            assert bad not in src, (name, bad)
    # And the unauthenticated adapter attaches nothing resembling a
    # credential, which would also change WHAT IS VISIBLE, making a published
    # sample unreproducible by anyone who does not hold the token.
    gl = read("gitlab.py")
    # No credential HEADER, as a quoted literal: the word appears in the
    # module's own comment saying there is none, which is why the check is for
    # the string a header would be built from and not for the word.
    assert not re.search(r"[\"']Authorization[\"']", gl), "a credential header"
    os.environ["GITLAB_URL"] = "https://gitlab.invalid"
    assert list(GitLabSource(pace=0).http.headers) == ["Accept"]
    del os.environ["GITLAB_URL"]
    envs = set(re.findall(r"os\.environ(?:\.get\(|\[)\s*.([A-Z][A-Z0-9_]*).",
                          gl))
    assert not {e for e in envs
                if any(w in e for w in ("TOKEN", "PASSWORD", "SECRET",
                                        "KEY"))}, envs
    assert "import base64" not in gl       # the raw endpoint answers text


def the_pacing_floors_cannot_be_configured_away():
    """A knob that can be set to zero is a knob that will be. Configuration
    may make a run gentler and must never make it sharper. The floors differ
    on purpose: an instance you operate and can watch is not the same as
    somebody else's production platform whose limits you cannot read."""
    assert GitLabSource.PACE_FLOOR > ForgejoSource.PACE_FLOOR, (
        GitLabSource.PACE_FLOOR, ForgejoSource.PACE_FLOOR)
    assert GitHubSource.PACE_FLOOR >= GitLabSource.PACE_FLOOR
    assert LocalSource.PACE_FLOOR == 0.0      # no network, nothing to pace
    for asked in ["0", "0.1", "-5", "", "nonsense"]:
        os.environ["TEST_PACE"] = asked
        assert base.pace_from_env("TEST_PACE", 1.0) == 1.0, asked
    os.environ["TEST_PACE"] = "3"
    assert base.pace_from_env("TEST_PACE", 1.0) == 3.0
    del os.environ["TEST_PACE"]
    # Enforced in the transport, not at the call sites, so no caller can
    # forget it.
    assert base.Fetcher("http://x", 0.0, 1.0).pace == 1.0
    assert base.Fetcher("http://x", 5.0, 1.0).pace == 5.0


def concurrency_is_the_request_rate_and_is_capped_per_source():
    """Pacing happens inside the worker, so the worker count IS the request
    rate. Two against a host you operate; none at all against one you do
    not."""
    assert ForgejoSource.WORKER_CEILING == 2
    assert GitLabSource.WORKER_CEILING == 1
    assert GitHubSource.WORKER_CEILING == 1
    for name in ("gitlab.py", "github.py"):
        src = read(name)
        for bad in ("ThreadPool", "concurrent", "Thread(", "threading"):
            assert bad not in src, (name, bad)
    # And the sweep clamps to the adapter's own ceiling rather than trusting
    # whoever passed --workers.
    local = LocalSource(FIXTURE_DIR)
    profiles, unknown = sweep(local, local.candidates()[:1], workers=99)
    assert len(profiles) + len(unknown) == 1


def forgejo_reads_emptiness_off_the_forges_own_flag():
    """The flag rides on the same listing the candidates came from, so it costs
    no second request against a host that is often CPU-capped. It is kept
    exactly as answered, None included."""
    os.environ["FORGE_URL"] = "https://forge.invalid"
    src = ForgejoSource(pace=0)
    del os.environ["FORGE_URL"]
    pages = [{"data": [{"full_name": "o/full", "empty": False, "size": 12},
                       {"full_name": "o/blank", "empty": True, "size": 0},
                       {"full_name": "o/silent", "size": 3}]}]
    calls = []

    def get(path, params=None, text=False, headers=None):
        calls.append(path)
        return 200, pages.pop(0), {}
    src.http.get = get
    repos = src.candidates()
    assert [r.key for r in repos] == ["o/full", "o/blank", "o/silent"]
    by_key = {r.key: r for r in repos}
    assert src.is_empty(by_key["o/full"]) is False
    assert src.is_empty(by_key["o/blank"]) is True
    # Listed without the flag: "the instance did not say", which is not
    # "not empty". Reading it as not-empty would invent the answer.
    assert src.is_empty(by_key["o/silent"]) is None
    # Never listed at all: nothing to decide on.
    assert src.is_empty(base.repo("o/absent")) is None
    assert calls == ["/repos/search"], calls


def gitlab_uses_a_documented_proxy_and_never_claims_empty():
    """`empty_repo` is not in an unauthenticated listing. The proxy decides the
    direction that matters (a default branch means not empty, which is what
    turns a 404 into a contradiction and sends the repository to unknown) and
    refuses the other, because a project with the repository feature disabled
    answers exactly like an empty one from outside."""
    os.environ["GITLAB_URL"] = "https://gitlab.invalid"
    src = GitLabSource(pace=0, sample=2)
    del os.environ["GITLAB_URL"]
    with_branch = base.repo("o/p", meta={"id": 1, "default_branch": "main"})
    without = base.repo("o/q", meta={"id": 2, "default_branch": None})
    assert src.is_empty(with_branch) is False
    assert src.is_empty(without) is None
    # Never True, for any shape of metadata: the claim is in the docstring and
    # it has to be true of the code.
    for meta in ({}, {"default_branch": ""}, {"empty_repo": True}):
        assert src.is_empty(base.repo("o/x", meta=meta)) is not True, meta


def github_reads_emptiness_off_its_own_404_and_not_off_size():
    """`size` is rounded to kilobytes, so a repository holding one small file
    can report 0. Reading that as empty would count real projects as doing no
    CI; unknown only costs a repository its place in the distribution."""
    src = GitHubSource(owners=["org"], token="t", pace=0)
    empty_repo = base.repo("org/blank", meta={"size_kb": 0})
    # Before anything is read, nothing is known.
    assert src.is_empty(empty_repo) is None

    def get(path, params=None, text=False, headers=None):
        return 404, json.dumps({"message": "This repository is empty.",
                                "status": "404"}), {}
    src.http.get = get
    status, entries, _ = src.tree(empty_repo)
    assert (status, entries) == (404, None)
    assert src.is_empty(empty_repo) is True
    # A 404 that says anything else is a failure to read, not an absence of
    # content, and a tiny repository is not an empty one.
    small = base.repo("org/small", meta={"size_kb": 0})

    def other(path, params=None, text=False, headers=None):
        return 404, json.dumps({"message": "Not Found"}), {}
    src.http.get = other
    src.tree(small)
    assert src.is_empty(small) is None
    # Stated against the code, not only in prose: nothing in is_empty() may
    # reach for the size field.
    body = read("github.py").split("def is_empty")[1]
    assert "size_kb" not in body and "meta.get" not in body, body


def github_excludes_profile_repositories_from_the_corpus():
    """Found when a first 25-repository sample returned 20 "no pipeline"
    results: 17 of the 25 were per-organisation `.github` metadata
    repositories, which sort early and contain no software. The lesson worth
    keeping is the general one (a prefix-ordered sample is not a sample), and
    the fix is to take them out of the denominator and SAY which."""
    src = GitHubSource(owners=["org"], token="t", pace=0)
    page = [{"full_name": "org/.github", "default_branch": "main"},
            {"full_name": "org/real", "default_branch": "main"},
            {"full_name": "org/tool", "default_branch": "main"}]

    def get(path, params=None, text=False, headers=None):
        return (200, page, {}) if params.get("page") == 1 else (200, [], {})
    src.http.get = get
    repos = src.candidates()
    assert [r.key for r in repos] == ["org/real", "org/tool"], repos
    assert src.excluded and src.excluded[0]["repo"] == "org/.github"
    assert "profile" in src.excluded[0]["reason"]
    # And a corpus has to be named: GitHub cannot be enumerated, so there is no
    # default and no guess at one.
    try:
        GitHubSource(token="t", pace=0).candidates()
    except sources.Refusal as e:
        assert "--owner" in str(e), e
    else:
        raise AssertionError("accepted an unnamed GitHub corpus")


def the_gitlab_sample_is_required_small_and_stratified():
    """A sample of twenty chosen badly is worse than none: twenty projects from
    one organisation's estate measure one team's house style and read as a
    reading of the corpus. So breadth comes first, and the organisation is the
    TOP-LEVEL path segment rather than the API's own namespace field, which
    names the immediate group several levels down."""
    os.environ["GITLAB_URL"] = "https://gitlab.invalid"
    src = GitLabSource(pace=0)
    del os.environ["GITLAB_URL"]
    # No default, at the point where it would be defaulted.
    for bad in (0, None):
        try:
            src.require_sample(bad)
        except sources.Refusal as e:
            assert "no default" in str(e), e
        else:
            raise AssertionError("accepted a missing sample size")
    src.require_sample(src.__class__ and 25)
    try:
        src.require_sample(26)
    except sources.Refusal as e:
        assert "ALLOW_LARGE_SAMPLE" in str(e), e
    else:
        raise AssertionError("accepted a size above the ceiling")

    def proj(pid, path, when, branch="main"):
        p = {"id": pid, "path_with_namespace": path, "last_activity_at": when}
        if branch:
            p["default_branch"] = branch
        return p
    # Deeply nested paths, as a corpus of organisation-published projects
    # really has them: the publisher is the first segment, and `namespace`
    # would say "team" for the first three.
    page = [proj(5, "orgC/newest", "2026-10-10T06:00:00Z", branch=None),
            proj(1, "big.example/team/a", "2026-10-10T05:00:00Z"),
            proj(2, "big.example/team/b", "2026-10-10T04:30:00Z"),
            proj(3, "big.example/team/c", "2026-10-10T04:00:00Z"),
            proj(4, "small/only", "2026-10-10T03:00:00Z"),
            proj(6, "third/one", "2026-10-10T02:00:00Z")]
    src.http.get = lambda *a, **k: (200, page, {})
    repos = src.candidates(limit=4)
    picked = [(p["organisation"], p["project"], p["picked_in_round"])
              for p in src.selection["projects"]]
    # Three publishers before the first one gets a second project, and the
    # first pick is the most recently active READABLE project overall.
    assert picked == [("big.example", "big.example/team/a", 1),
                      ("small", "small/only", 1),
                      ("third", "third/one", 1),
                      ("big.example", "big.example/team/b", 2)], picked
    assert len(repos) == 4
    # The one listed without a default branch is skipped and SAID to be
    # skipped, even though it is the most recently active project of all: an
    # output that stayed quiet would look like the sample had simply missed it.
    assert [p["project"] for p in
            src.selection["skipped_no_default_branch"]] == ["orgC/newest"]
    for want in ("last_activity_at", "TOP-LEVEL", "organisation"):
        assert want in src.selection["rule"], want


def the_local_adapter_finds_both_corpus_layouts():
    """A corpus on disk is written either way, so each top-level directory is
    judged on its own and neither layout needs a flag."""
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "flat", ".github", "workflows"))
    open(os.path.join(root, "flat", ".github", "workflows", "ci.yml"),
         "w").write("on: [pull_request]\njobs:\n  a:\n    steps:\n"
                    "      - run: make test\n")
    os.makedirs(os.path.join(root, "owner", "repo", ".github", "workflows"))
    open(os.path.join(root, "owner", "repo", ".github", "workflows", "c.yml"),
         "w").write("on: [pull_request]\njobs:\n  a:\n    steps:\n"
                    "      - run: make test\n")
    os.makedirs(os.path.join(root, "hollow"))
    src = LocalSource(root)
    keys = sorted(r.key for r in src.candidates())
    assert keys == ["flat", "hollow", "owner/repo"], keys
    by_key = {r.key: r for r in src.candidates()}
    # A directory holding nothing is empty; one that is not there is unknown.
    assert src.is_empty(by_key["hollow"]) is True
    assert src.is_empty(by_key["flat"]) is False
    assert src.is_empty(base.repo("nothing/here")) is None
    profiles, unknown = sweep(src, src.candidates())
    assert unknown == {}, unknown
    assert profiles["flat"][PR_SCOPE]["primary"] == "self-contained"
    assert profiles["hollow"][PR_SCOPE]["primary"] == NO_PIPELINE
    assert src.offline is True and src.describe()["offline"] is True


def the_fixtures_classify_the_same_through_the_local_adapter():
    """The fixture corpus read as the sweep reads a corpus, rather than by the
    fixture loader's own shortcut. Both paths have to agree, or the fixture
    suite is testing something the tool does not do."""
    src = LocalSource(FIXTURE_DIR)
    repos = [r for r in src.candidates() if r.key != "expected.txt"]
    profiles, unknown = sweep(src, repos)
    assert unknown == {}, unknown
    direct = {k: classify(v) for k, v in fixture_cases().items()}
    assert set(profiles) == set(direct), (set(profiles) ^ set(direct))
    for key in sorted(direct):
        for scope in (PR_SCOPE, REPO_SCOPE):
            assert profiles[key][scope] == direct[key][scope], key


def an_unreadable_repository_is_unknown_never_no_pipeline():
    """Getting this backwards is the expensive mistake: an unreadable
    repository counted as no-pipeline turns every transient 503 into evidence
    of an absent pipeline, and no-pipeline is the number that gets quoted."""
    class Stub(sources.Source):
        name = "stub"

        def __init__(self, root_status, empty=None, dir_status=200,
                     file_status=200):
            self.root_status, self.empty_answer = root_status, empty
            self.dir_status, self.file_status = dir_status, file_status

        def tree(self, repo, path=""):
            if not path:
                if self.root_status != 200:
                    return self.root_status, None, False
                return 200, [sources.Entry(".github", "dir")], False
            if self.dir_status != 200:
                return self.dir_status, None, False
            return 200, [sources.Entry("ci.yml", "file")], False

        def file_text(self, repo, path):
            if self.file_status != 200:
                return self.file_status, None
            return 200, "on: [pull_request]\njobs:\n  a:\n    steps:\n"

        def is_empty(self, repo):
            return self.empty_answer

    r = base.repo("o/r")
    for status in (503, 0, 403, 500):
        files, other, reason, got = fetch_repo(Stub(status), r)
        assert files is None and str(status) in reason, (status, reason)
    # The one exception, and the reason it is read off the repository rather
    # than off the status code.
    files, other, reason, _ = fetch_repo(Stub(404, empty=True), r)
    assert reason is None and files == {}, (files, reason)
    assert classify(files)[PR_SCOPE]["primary"] == NO_PIPELINE
    files, _o, reason, _ = fetch_repo(Stub(404, empty=False), r)
    assert files is None and "not empty" in reason, reason
    files, _o, reason, _ = fetch_repo(Stub(404, empty=None), r)
    assert files is None and "did not say" in reason, reason
    # A workflow directory that lists but whose files will not read is the
    # subtler half: the repository plainly has CI, and the file that would not
    # load is as likely as any other to be the one carrying the highest signal.
    files, _o, reason, _ = fetch_repo(Stub(200, file_status=503), r)
    assert files is None and "ci.yml" in reason and "503" in reason, reason
    files, _o, reason, _ = fetch_repo(Stub(200, dir_status=503), r)
    assert files is None and "503" in reason, reason
    # And the verdict table on its own, since a cached re-analysis re-runs it.
    assert empty_verdict(404, True) == ({}, [], None)
    assert empty_verdict(404, False)[2].endswith(
        "an unborn or missing default branch reads this way")
    assert "did not say" in empty_verdict(404, None)[2]
    assert empty_verdict(500, True)[2] == "root listing HTTP 500"


def the_outputs_refuse_each_others_names():
    """A sweep costs hours, so a mode that overwrote another mode's output
    would destroy a run in progress with no error anywhere. Refused BY
    BASENAME, which is what lets this check prove the property while aiming
    every write at a scratch directory (see EXPERIMENTS.md, "A destructive
    test")."""
    scratch = tempfile.mkdtemp()
    for name in sorted(report.ALL_OUTPUT_NAMES - {report.PROFILE_NAME}):
        try:
            report.write(os.path.join(scratch, name), {}, {})
        except SystemExit as e:
            assert "refusing" in str(e), e
        else:
            raise AssertionError("wrote to " + name)
    assert os.listdir(scratch) == [], os.listdir(scratch)
    # The one it is allowed to write, so the guard is not simply refusing
    # everything.
    report.write(os.path.join(scratch, report.PROFILE_NAME), {}, {})
    assert os.listdir(scratch) == [report.PROFILE_NAME]


sys.exit(run([
    ("every adapter is read-only by construction", read_only_by_construction),
    ("the pacing floors cannot be configured away",
     the_pacing_floors_cannot_be_configured_away),
    ("concurrency is the request rate, and is capped per source",
     concurrency_is_the_request_rate_and_is_capped_per_source),
    ("forgejo: emptiness comes off the forge's own flag",
     forgejo_reads_emptiness_off_the_forges_own_flag),
    ("gitlab: a documented proxy that never claims empty",
     gitlab_uses_a_documented_proxy_and_never_claims_empty),
    ("github: emptiness off its own 404, and never off size",
     github_reads_emptiness_off_its_own_404_and_not_off_size),
    ("github: organisation profile repositories leave the denominator",
     github_excludes_profile_repositories_from_the_corpus),
    ("gitlab: the sample is required, small and stratified",
     the_gitlab_sample_is_required_small_and_stratified),
    ("local: both corpus layouts are found, and emptiness is honest",
     the_local_adapter_finds_both_corpus_layouts),
    ("local: the fixtures classify the same through the adapter",
     the_fixtures_classify_the_same_through_the_local_adapter),
    ("an unreadable repository is unknown, never no-pipeline",
     an_unreadable_repository_is_unknown_never_no_pipeline),
    ("the output files refuse each other's names",
     the_outputs_refuse_each_others_names),
]))
