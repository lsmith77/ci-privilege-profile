#!/usr/bin/env python3
"""The outputs. Two profiles are no use if a reader cannot tell which answers
the question, and a caveat that lives only in a docstring is not a caveat.

Every check here is about something reaching the reader: the printed summary is
what a person reviews a rule change against, and the JSON is what somebody
finds months later and re-derives a number from.
"""
import contextlib
import io
import json
import os
import sys
import tempfile

import harness
from harness import run

harness.offline()

from ciprofile import report                                     # noqa: E402
from ciprofile.classify import (ASIDE, ASSUMES_TOOLCHAIN,        # noqa: E402
                                NO_PULL_REQUEST_TRIGGER, PRECEDENCE,
                                PR_SCOPE, REPO_SCOPE,
                                USES_FORGE_TOKEN, classify,
                                contributor_runnable, forge_token_split)
from ciprofile.fixtures import fixture_cases                     # noqa: E402

REPOS = {"o/" + k: classify(v) for k, v in fixture_cases().items()}


def printed():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report.report({}, REPOS, {})
    return out.getvalue()


def both_scopes_reach_the_reader_and_say_which_to_quote():
    split = [k for k, p in REPOS.items()
             if p[PR_SCOPE]["primary"] != p[REPO_SCOPE]["primary"]]
    assert split, "no fixture differs between the scopes, so nothing tests it"
    said = printed()
    for want in ["PULL-REQUEST SCOPE", "THE FIGURE TO QUOTE", "WHOLE REPOSITORY",
                 "NOT the figure to quote", NO_PULL_REQUEST_TRIGGER,
                 "a pipeline, but nothing a pull request triggers",
                 "bare container", ASSUMES_TOOLCHAIN]:
        assert want in said, (want, said)
    # Two TABLES, not two headings: a heading over a table that was never
    # printed is the failure mode worth catching, since the headings are what
    # say which figure to quote. Every class is counted in both, bar the one
    # that can only arise in the pull-request scope.
    width = max(len(x) for x in PRECEDENCE + ASIDE)
    for cls in PRECEDENCE:
        want = 1 if cls == NO_PULL_REQUEST_TRIGGER else 2
        row = "  " + cls.ljust(width) + "  "
        assert said.count(row) == want, (cls, said.count(row), want)
    for flag in ASIDE:
        row = "    " + flag.ljust(width) + "  "
        assert said.count(row) == 2, (flag, said.count(row))
    d = tempfile.mkdtemp()
    path = report.write(os.path.join(d, report.PROFILE_NAME), REPOS, {})
    got = json.load(open(path))
    for _key, prof in got["repos"].items():
        for scope in (PR_SCOPE, REPO_SCOPE):
            assert set(prof[scope]) == {"primary", "flags", "signals",
                                        "files"}, prof
    for want in [PR_SCOPE, REPO_SCOPE, "figure to quote",
                 NO_PULL_REQUEST_TRIGGER, ASSUMES_TOOLCHAIN,
                 "bare container"]:
        assert want in got["$comment"], want


def the_forge_token_split_is_reported_in_both_places():
    """The carve-out is the judgement that most moves the headline, so the
    number that sizes the disagreement has to travel with the figures. The
    printed summary is the review gate; the JSON is what anyone re-deriving the
    headline reads."""
    total, with_write, without_write = forge_token_split(REPOS)
    assert total == with_write + without_write
    assert with_write and without_write, (with_write, without_write)
    said = printed()
    width = max(len(x) for x in PRECEDENCE + ASIDE)
    for want in ["  %s  %5d" % (USES_FORGE_TOKEN.ljust(width), total),
                 "of the %d referencing the forge" % total,
                 "%5d also carry a forge-write signal" % with_write,
                 "%5d carry no forge-write signal" % without_write,
                 "what a stricter reading would count as needing a credential"]:
        assert want in said, (want, said)
    d = tempfile.mkdtemp()
    got = json.load(open(report.write(
        os.path.join(d, report.PROFILE_NAME), REPOS, {})))
    assert got["forge_token"] == {"repos": total,
                                  "with_forge_write": with_write,
                                  "without_forge_write": without_write}, got
    assert "forge_token" in got["$comment"]


def the_contributor_runnable_figure_is_reported_with_its_band():
    """Printed beside the distribution and never alone: the unclear count is
    part of the answer, and in every corpus this has been run against it is the
    largest of the three numbers. EXPERIMENTS.md carries why."""
    total, plain, reporting, unclear = contributor_runnable(REPOS)
    assert total == plain + reporting
    assert plain and reporting and unclear, (plain, reporting, unclear)
    said = printed()
    width = max(len(x) for x in PRECEDENCE + ASIDE)
    label = "contributor-runnable if reporting steps are dropped"
    for want in ["  %s  %5d" % (label.ljust(width), total),
                 "= %d self-contained + %d whose every privileged step is "
                 "reporting" % (plain, reporting),
                 "%d credentials-unclear" % unclear,
                 "uncertainty band is wide"]:
        assert want in said, (want, said)
    d = tempfile.mkdtemp()
    got = json.load(open(report.write(
        os.path.join(d, report.PROFILE_NAME), REPOS, {})))
    assert got["contributor_runnable"][PR_SCOPE] == {
        "repos": total, "self_contained": plain, "reporting_only": reporting,
        "unclear": unclear}, got["contributor_runnable"]
    assert REPO_SCOPE in got["contributor_runnable"]
    assert "contributor_runnable" in got["$comment"]
    assert "credentials-unclear" in got["$comment"]


def a_partial_run_says_so_in_the_file():
    """A distribution over an unannounced subset is the one output worth less
    than no output, because nothing about it looks wrong."""
    d = tempfile.mkdtemp()
    got = json.load(open(report.write(
        os.path.join(d, report.PROFILE_NAME), REPOS, {}, limited=True)))
    assert got["partial"] is True
    assert "prefix of the corpus" in got["$comment"]
    full = json.load(open(report.write(
        os.path.join(d, report.PROFILE_NAME), REPOS, {})))
    assert full["partial"] is False


def the_sources_limitations_travel_with_the_figures():
    """A limitation that lives only in a module docstring is not one: the
    terminal scrolls away and the JSON is what somebody finds later."""
    from ciprofile.sources.local import LocalSource
    from ciprofile.fixtures import FIXTURE_DIR
    src = LocalSource(FIXTURE_DIR)
    d = tempfile.mkdtemp()
    got = json.load(open(report.write(
        os.path.join(d, report.PROFILE_NAME), REPOS, {}, source=src)))
    assert got["source"]["limitations"] == src.limitations
    assert got["source"]["read_only"] is True
    assert got["source"]["offline"] is True
    assert "structural_parser" in got
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report.report({}, REPOS, {}, source=src)
    assert "LIMITATION:" in out.getvalue()


def the_previous_profile_is_read_only_to_diff_against():
    """Never fatal: the point of a re-run is the rule change it shows, and a
    profile that cannot be parsed is a reason to show the distribution without
    a comparison rather than to refuse to show it."""
    d = tempfile.mkdtemp()
    bad = os.path.join(d, "broken.json")
    open(bad, "w").write("{ not json")
    assert report.previous_profile(bad) == {}
    assert report.previous_profile(os.path.join(d, "absent.json")) == {}
    path = report.write(os.path.join(d, report.PROFILE_NAME), REPOS, {})
    before = report.previous_profile(path)
    assert set(before) == set(REPOS)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report.report(before, REPOS, {})
    assert "no change since the previous profile" in out.getvalue()
    # And a moved repository is named, with both scopes, because that line is
    # the whole review of a rule change.
    moved = dict(REPOS)
    key = sorted(REPOS)[0]
    moved[key] = classify({})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report.report(before, moved, {})
    assert "CHANGED " + key in out.getvalue(), out.getvalue()


sys.exit(run([
    ("both scopes reach the reader, and say which to quote",
     both_scopes_reach_the_reader_and_say_which_to_quote),
    ("the forge-token split is reported, in the summary and the JSON",
     the_forge_token_split_is_reported_in_both_places),
    ("the contributor-runnable figure is reported with its band",
     the_contributor_runnable_figure_is_reported_with_its_band),
    ("a partial run says so in the file", a_partial_run_says_so_in_the_file),
    ("a source's limitations travel with the figures",
     the_sources_limitations_travel_with_the_figures),
    ("the previous profile is read only to diff against",
     the_previous_profile_is_read_only_to_diff_against),
]))
