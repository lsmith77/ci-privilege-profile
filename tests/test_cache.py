#!/usr/bin/env python3
"""The evidence cache: what it has to carry, and what it refuses to do.

A sweep of a sizeable corpus is an hour and a half of paced requests, so the
cache is what makes a rule change affordable. What has to hold is that it
carries ENOUGH: the same corpus re-classified from it must reproduce the
sweep's own profile exactly, with the network taken away rather than merely
unused.
"""
import contextlib
import io
import json
import os
import socket
import sys
import tempfile

import harness
from harness import run

from ciprofile import cache as cachemod                          # noqa: E402
from ciprofile import report, sources                             # noqa: E402
from ciprofile.classify import (NO_PIPELINE, PR_SCOPE, REPO_SCOPE)  # noqa: E402
from ciprofile.sources.local import LocalSource                  # noqa: E402
from ciprofile.sweep import sweep                                # noqa: E402

WF = ("on:\n  pull_request:\njobs:\n  t:\n    runs-on: ubuntu-latest\n"
      "    steps:\n      - run: pytest -q --cov\n"
      "      - uses: codecov/codecov-action@v4\n        with:\n"
      "          token: ${{ secrets.CODECOV_TOKEN }}\n")


class StubSource(sources.Source):
    """One repository with CI, one empty, and a foreign-CI marker at the root.

    A stub rather than a live adapter, because what is being tested is the
    cache and not anybody's API.
    """
    name = "stub"

    def candidates(self, limit=0):
        return [sources.repo("o/one"), sources.repo("o/empty")]

    def tree(self, repo, path=""):
        if repo.key == "o/empty":
            return 404, None, False
        if not path:
            return 200, [sources.Entry(".github", "dir"),
                         sources.Entry(".travis.yml", "file")], False
        if path == ".github/workflows":
            return 200, [sources.Entry("test.yml", "file")], False
        return 404, None, False

    def file_text(self, repo, path):
        return 200, WF

    def is_empty(self, repo):
        return repo.key == "o/empty"


def a_stubbed_sweeps_cache_reproduces_its_profile_with_no_network():
    d = tempfile.mkdtemp()
    profile = os.path.join(d, report.PROFILE_NAME)
    cache_path = os.path.join(d, report.CACHE_NAME)
    src = StubSource()
    recorder = cachemod.Recorder(src.describe())
    repos = src.candidates()
    profiles, unknown = sweep(src, repos, recorder=recorder)
    report.write(profile, profiles, unknown, src)
    recorder.write(cache_path, covered=set(profiles) | set(unknown),
                   log=lambda _m: None)
    sweep_doc = json.load(open(profile))
    cache = json.load(open(cache_path))
    # Everything the classification and the scoping read, and nothing else: the
    # texts, the foreign-CI markers, the root status and the source's own
    # emptiness answer, which is what the 404-versus-empty rule consults.
    assert cache["partial"] is False, cache["partial_reason"]
    one = cache["repos"]["o/one"]
    assert one["files"] == {".github/workflows/test.yml": WF}, one
    assert one["other_ci"] == [".travis.yml"] and one["root_status"] == 200
    assert one["empty"] is False and one["fetched"], one
    # The empty repository keeps its INGREDIENTS rather than a stored
    # conclusion, so the rule that reads them can be changed and re-run.
    assert cache["repos"]["o/empty"]["root_status"] == 404
    assert cache["repos"]["o/empty"]["empty"] is True
    assert "files" not in cache["repos"]["o/empty"]

    # Now the re-analysis, with the socket layer gone.
    cachemod.forbid_network("the cached re-analysis reached the network")
    local = LocalSource(cache_path)
    again_profiles, again_unknown = sweep(local, local.candidates())
    out = report.write(os.path.join(d, report.FROM_CACHE_NAME),
                       again_profiles, again_unknown, local,
                       cache=local.cache)
    again = json.load(open(out))
    # Byte-identical where it counts: the classification. The provenance header
    # is the one thing that MUST differ, and the next check is that it does.
    for key in ("repos", "unknown", "contributor_runnable", "forge_token"):
        assert json.dumps(sweep_doc[key], indent=1, sort_keys=True) == \
            json.dumps(again[key], indent=1, sort_keys=True), key
    assert again["repos"]["o/empty"][PR_SCOPE]["primary"] == NO_PIPELINE
    # Its own file, and the sweep's profile untouched: a run in progress must
    # not lose its output, and nobody reading the profile later should have to
    # wonder whether it was measured or re-derived.
    assert again["from_cache"] is True and "from_cache" not in sweep_doc
    assert os.path.basename(out) != report.PROFILE_NAME
    try:
        report.write(os.path.join(d, report.PROFILE_NAME), {}, {},
                     cache=local.cache)
    except SystemExit as e:
        assert "refusing" in str(e), e
    else:
        raise AssertionError("wrote the cached re-analysis over the profile")


def every_output_says_it_came_from_a_cache_and_when():
    """A cached re-analysis describes the corpus as it was on the fetch date,
    and corpora move. The JSON outlives the terminal, so the date travels with
    it: in the first key a reader's eye lands on, in `scanned` (which has
    always meant when the corpus was read, not when the rules ran), and above
    and below the figures in the printed summary."""
    d = tempfile.mkdtemp()
    cache = {"cache_version": cachemod.CACHE_VERSION,
             "fetched_oldest": "2026-09-01", "fetched_newest": "2026-10-10",
             "partial": False, "repos": {}}
    line = cachemod.banner(cache)
    for want in ("CACHE", "2026-09-01", "2026-10-10", "NOT as it is now",
                 "NOT a fresh measurement"):
        assert want in line, (want, line)
    from ciprofile.classify import classify
    repos = {"o/r": classify({})}
    path = report.write(os.path.join(d, report.FROM_CACHE_NAME), repos, {},
                        cache=cache)
    got = json.load(open(path))
    assert got["$comment"].startswith(line), got["$comment"][:80]
    assert got["from_cache"] is True and got["scanned"] == "2026-09-01", got
    assert got["reanalysed"] != got["scanned"], got
    assert got["cache_fetched"] == ["2026-09-01", "2026-10-10"], got
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report.report({}, repos, {}, cache=cache)
    said = [l for l in out.getvalue().splitlines() if l.strip()]
    # Above and below the figures both: the terminal scrolls, and a reader
    # coming at the distribution from either end has to meet the date before
    # the numbers.
    assert line in said[0], said[0]
    assert line in said[-1], said[-1]
    # A partial cache says so in the same breath, wherever the banner goes.
    cache["partial"] = True
    cache["partial_reason"] = "interrupted mid-sweep"
    loud = cachemod.banner(cache)
    assert "PARTIAL" in loud and "interrupted mid-sweep" in loud, loud


def a_network_call_is_impossible_not_just_unintended():
    """The guarantee is the mode's whole claim, so it is taken away rather than
    promised: a docstring cannot stop a later edit from reaching for one more
    field, and against a CPU-capped instance nobody would notice if it did."""
    cachemod.forbid_network("refused")
    for what, call in [
            ("connect", lambda: socket.socket().connect(("h", 1))),
            ("connect_ex", lambda: socket.socket().connect_ex(("h", 1))),
            ("create_connection",
             lambda: socket.create_connection(("h", 1))),
            ("resolve", lambda: socket.getaddrinfo("h", 1)),
            ("gethostbyname", lambda: socket.gethostbyname("h"))]:
        try:
            call()
        except AssertionError as e:
            assert "refused" in str(e), (what, e)
        else:
            raise AssertionError("%s still reached out" % what)
    # And the cache path names no fetcher, which is the kind of thing a later
    # convenience edit would undo.
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "ciprofile", "cache.py")).read()
    for bad in ("urlopen", "urllib", "Fetcher", "http.get"):
        assert bad not in src, bad


def a_missing_unreadable_stale_or_partial_cache_is_refused():
    """Refusing is the whole policy here. The alternative is a distribution
    over an unannounced subset of the corpus, which is the one output worth
    less than no output: nothing about it looks wrong, and it would be
    quoted."""
    d = tempfile.mkdtemp()
    dated = {"fetched_oldest": "2026-10-10", "fetched_newest": "2026-10-10"}

    def refused(name, body, want):
        p = os.path.join(d, name)
        if body is not None:
            open(p, "w").write(body)
        try:
            cachemod.read_cache(p)
        except SystemExit as e:
            assert want in str(e), (name, e)
        else:
            raise AssertionError("%s was accepted" % name)
    refused("absent.json", None, "no cache at")
    refused("corrupt.json", "{ not json", "unreadable")
    refused("stale.json", json.dumps(dict(dated, cache_version=0,
                                          repos={"o/r": {}})), "cache_version")
    refused("nothing.json",
            json.dumps(dict(dated, cache_version=cachemod.CACHE_VERSION,
                            repos={})), "no repositories")
    # An undated cache is refused outright: nothing produced from it could say
    # how old its corpus is, which makes it indistinguishable from a
    # measurement.
    refused("undated.json",
            json.dumps({"cache_version": cachemod.CACHE_VERSION,
                        "repos": {"o/r": {}}}), "when it was")
    part = json.dumps(dict(dated, cache_version=cachemod.CACHE_VERSION,
                           repos={"o/r": {}}, partial=True,
                           partial_reason="interrupted mid-sweep"))
    refused("partial.json", part, "marked partial")
    # Overridable, because a deliberately smaller corpus is somebody's decision
    # to make, and then every output carries the reason.
    cachemod.ALLOW_PARTIAL_CACHE = True
    try:
        got = cachemod.read_cache(os.path.join(d, "partial.json"))
        assert got["partial"] is True
        assert "interrupted mid-sweep" in cachemod.banner(got)
    finally:
        cachemod.ALLOW_PARTIAL_CACHE = False


def a_carried_forward_profile_with_no_texts_makes_the_cache_partial():
    """The incremental case is where a cache quietly stops covering the corpus:
    a profile carried forward brings no pipeline texts with it. The cache says
    so rather than looking complete over a subset."""
    rec = cachemod.Recorder({"source": "stub"})
    rec.record("o/fresh", 200, False, {}, [], None)
    doc = rec.document(covered={"o/fresh"})
    assert doc["partial"] is False, doc["partial_reason"]
    doc = rec.document(covered={"o/fresh", "o/textless"})
    assert doc["partial"] is True, doc
    assert "carried forward" in doc["partial_reason"], doc["partial_reason"]


harness.offline()
sys.exit(run([
    ("a stubbed sweep's cache reproduces its profile with no network",
     a_stubbed_sweeps_cache_reproduces_its_profile_with_no_network),
    ("every cached output says it came from a cache, and when",
     every_output_says_it_came_from_a_cache_and_when),
    ("a network call is impossible, not just unintended",
     a_network_call_is_impossible_not_just_unintended),
    ("a missing, unreadable, stale, undated or partial cache is refused",
     a_missing_unreadable_stale_or_partial_cache_is_refused),
    ("a carried-forward profile with no texts makes the cache partial",
     a_carried_forward_profile_with_no_texts_makes_the_cache_partial),
]))
