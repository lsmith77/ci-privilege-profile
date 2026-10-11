#!/usr/bin/env python3
"""The fixture corpus, and the expectation table it is checked against.

    python3 -m ciprofile --fixtures

Offline by construction: no host call anywhere on this path, which is why it is
reachable with no credential and why anybody can run the test suite.

Each fixture is a synthetic repository, laid out as a repository, because the
*path* is what decides which grammar a file is read with. One subdirectory per
case; a case holding no pipeline file is the no-pipeline case.

The expectation table is the point of the corpus rather than its paperwork.
Adding a signal that moves one of its lines makes the blast radius of a rule
change visible in a diff, which is the only review available for a change
whose real effect is a distribution over somebody else's corpus.
"""
import os

from .classify import PR_SCOPE, REPO_SCOPE, classify
from .structure import kind_of

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(os.path.dirname(HERE), "fixtures", "ci")


def fixture_cases(root=FIXTURE_DIR):
    """{case name: {path relative to the case: text}} from a fixture tree."""
    cases = {}
    for case in sorted(os.listdir(root)):
        base = os.path.join(root, case)
        if not os.path.isdir(base):
            continue
        files = {}
        for dirpath, _dirs, names in os.walk(base):
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                rel = os.path.relpath(full, base)
                if kind_of(rel):
                    with open(full) as fh:
                        files[rel] = fh.read()
        cases[case] = files
    return cases


def load_expected(path):
    """{case: {scope: (primary, [flags])}} from the expectation table.

    A row carries the pull-request scope then the whole repository. Where the
    two agree the row may give one pair and stand for both, which is most of
    the table. Spelling identical columns out twice invites them to be read as
    a distinction that is being made.
    """
    expected = {}
    with open(path) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            pair = (parts[1], sorted(parts[2].split(",")))
            if len(parts) > 3:
                expected[parts[0]] = {
                    PR_SCOPE: pair,
                    REPO_SCOPE: (parts[3], sorted(parts[4].split(","))),
                }
            else:
                expected[parts[0]] = {PR_SCOPE: pair, REPO_SCOPE: pair}
    return expected


def check(root=FIXTURE_DIR, log=print, verbose=True):
    """0 if every fixture classifies as the table says, 1 otherwise."""
    cases = fixture_cases(root)
    expected = load_expected(os.path.join(root, "expected.txt"))
    width = max([len(c) for c in cases] + [7])
    if verbose:
        log("{:<{w}}  {:<13}  {:<23}  flags".format(
            "fixture", "scope", "primary", w=width + 1))
    bad = []
    for case, files in sorted(cases.items()):
        prof = classify(files)
        got = {s: (prof[s]["primary"], sorted(prof[s]["flags"]))
               for s in (PR_SCOPE, REPO_SCOPE)}
        mark = " "
        if case not in expected:
            mark = "?"
            bad.append((case, "no expectation recorded"))
        elif got != expected[case]:
            mark = "x"
            for scope in (PR_SCOPE, REPO_SCOPE):
                if got[scope] != expected[case][scope]:
                    want = expected[case][scope]
                    bad.append((case, "{} scope: expected {} [{}], got {} [{}]"
                                .format(scope, want[0], ",".join(want[1]),
                                        got[scope][0],
                                        ",".join(got[scope][1]))))
        label = case
        for scope in (PR_SCOPE, REPO_SCOPE):
            sub = prof[scope]
            if verbose:
                log("{}{:<{w}}  {:<13}  {:<23}  {}".format(
                    mark, label, scope, sub["primary"],
                    ",".join(sub["flags"]), w=width))
                log(" {:<{w}}  {:<13}  signals: {}".format(
                    "", "", ",".join(sub["signals"]) or "-", w=width))
            mark, label = " ", ""
    for case in sorted(set(expected) - set(cases)):
        bad.append((case, "expected but no such fixture"))
    if bad:
        log("\nMISMATCH:")
        for case, note in bad:
            log("  {}: {}".format(case, note))
        return 1
    log("\n{} fixtures classify as expected".format(len(cases)))
    return 0
