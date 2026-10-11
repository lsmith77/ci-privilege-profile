#!/usr/bin/env python3
"""The fixture corpus itself, and the agreement between the two readings.

The expectation table is the review gate for a rule change: a rule whose real
effect is a distribution over somebody else's corpus has no other diff.
"""
import contextlib
import io
import os
import sys

import harness
from harness import run

harness.offline()

from ciprofile.classify import PR_SCOPE, REPO_SCOPE, classify    # noqa: E402
from ciprofile.fixtures import (FIXTURE_DIR, check,              # noqa: E402
                                fixture_cases, load_expected)
from ciprofile.structure import (actions_commands, actions_steps,  # noqa: E402
                                 actions_triggers, gitlab_commands,
                                 gitlab_jobs, kind_of, privilege_units,
                                 units_with_scope)


def every_fixture_classifies_as_the_table_says():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = check(verbose=False)
    assert rc == 0, out.getvalue()
    return "{} fixtures".format(len(fixture_cases()))


def the_table_and_the_corpus_cover_each_other():
    """A row with no fixture is a decision nothing enforces; a fixture with no
    row is a class nothing pins."""
    cases = set(fixture_cases())
    expected = set(load_expected(os.path.join(FIXTURE_DIR, "expected.txt")))
    assert cases == expected, cases ^ expected


def every_class_and_every_aside_flag_has_a_fixture():
    """Otherwise a class can be removed, or quietly stop being reachable, and
    nothing fails."""
    from ciprofile.classify import ASIDE, PRECEDENCE
    seen = set()
    for files in fixture_cases().values():
        prof = classify(files)
        for scope in (PR_SCOPE, REPO_SCOPE):
            seen |= set(prof[scope]["flags"])
    missing = (set(PRECEDENCE) | set(ASIDE)) - seen
    assert not missing, missing


def both_structural_readings_agree_on_every_fixture():
    """The parser-backed reading and the line reader must produce the same
    profile for every fixture, or the suite is testing one of them and shipping
    the other.

    Where they can still differ is the long tail of shapes a line reader cannot
    see. When the two were run over a 1428-repository corpus, exactly one
    repository moved, in the under-claiming direction: a flow sequence written
    on the line after `on:` reads as undeterminable to the line reader, which
    keeps the file in the pull-request scope. Skipped where no parser is
    installed, and never silently passed.
    """
    harness.needs_parser()
    from ciprofile import structure
    cases = fixture_cases()
    with_parser = {k: classify(v) for k, v in cases.items()}
    saved = structure._yaml
    structure._yaml = None
    try:
        without = {k: classify(v) for k, v in cases.items()}
    finally:
        structure._yaml = saved
    assert with_parser == without, [k for k in cases
                                    if with_parser[k] != without[k]]
    # And the one shape the parser reads where the line reader cannot, stated
    # as a check so the difference is documented rather than discovered.
    flow_on_next_line = "on:\n   [push]\njobs:\n  a:\n    steps:\n"
    assert actions_triggers(flow_on_next_line) == {"push"}
    structure._yaml = None
    try:
        assert actions_triggers(flow_on_next_line) is None
    finally:
        structure._yaml = saved


def the_fixture_paths_decide_the_grammar():
    """The corpus is laid out as repositories rather than as a pile of YAML
    because the *path* is what decides which grammar a file is read with."""
    cases = fixture_cases()
    kinds = {}
    for case, files in cases.items():
        for path in files:
            kinds[kind_of(path)] = kinds.get(kind_of(path), 0) + 1
    assert kinds.get("actions") and kinds.get("gitlab"), kinds
    assert None not in kinds, kinds
    # Each workflow location is exercised, since the location is what the
    # discovery order turns on.
    paths = [p for f in cases.values() for p in f]
    assert any(p.startswith(".forgejo/") for p in paths), paths
    assert any(p.startswith(".github/") for p in paths), paths
    assert any(p == ".gitlab-ci.yml" for p in paths), paths


def the_unit_readings_do_not_crash_on_either_grammar():
    """Cheap, and it has caught a real thing: a reading that returns an empty
    list on every input passes a classification test whose expectations were
    recorded while it was broken."""
    cases = fixture_cases()
    steps = jobs = runs = cmds = 0
    for case, files in cases.items():
        for path, text in files.items():
            if kind_of(path) == "gitlab":
                got, _frame = gitlab_jobs(text)
                jobs += len(got)
                cmds += len(gitlab_commands(text))
            else:
                got, _frame = actions_steps(text)
                steps += len(got)
                runs += len(actions_commands(text))
    assert steps > 50 and runs > 20, (steps, runs)
    assert jobs >= 3 and cmds >= 3, (jobs, cmds)
    # The scope-aware reading cuts the same units, and places every one of them
    # across the corpus. A None scope is the refusal the test-step
    # determination takes the privileged way, so a corpus-wide None would be a
    # segmentation that never works rather than a rule that is careful.
    for case, files in cases.items():
        for path, text in files.items():
            kind = kind_of(path)
            scoped = units_with_scope(kind, text)
            units, _frame = privilege_units(kind, text)
            assert [u for u, _s in scoped] == units, (case, path)
            assert all(s is not None for _u, s in scoped), (case, path)


sys.exit(run([
    ("every fixture classifies as the table says",
     every_fixture_classifies_as_the_table_says),
    ("the table and the corpus cover each other",
     the_table_and_the_corpus_cover_each_other),
    ("every class and every aside flag has a fixture",
     every_class_and_every_aside_flag_has_a_fixture),
    ("both structural readings agree on every fixture",
     both_structural_readings_agree_on_every_fixture),
    ("the fixture paths decide the grammar",
     the_fixture_paths_decide_the_grammar),
    ("the unit readings return units for both grammars",
     the_unit_readings_do_not_crash_on_either_grammar),
]))
