#!/usr/bin/env python3
"""A test harness small enough to read in one sitting.

No framework, for two reasons. The suite has to run on a bare checkout with
nothing installed, which is the same constraint the fetching side holds to; and
every check here exists because something specific went wrong, so each one
carries the comment saying what, and a runner that hid those comments behind
test ids would lose the only documentation they have.

Every test file takes the socket layer away before it does anything. A stub
that quietly fell through to a real forge would then fail here rather than spend
somebody's rate budget from a test run.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ciprofile.cache import forbid_network          # noqa: E402
from ciprofile.structure import parser_available    # noqa: E402


def offline():
    """No network from a test, asserted rather than intended."""
    forbid_network("a test reached the network")


def run(checks):
    """[(label, callable)] -> process exit code.

    A check passes by returning without raising. The traceback is printed on
    failure, because a check that says only "something is wrong" sends the
    reader to the source instead of to the defect.
    """
    failed = skipped = 0
    for label, fn in checks:
        try:
            result = fn()
        except SkipCheck as e:
            skipped += 1
            print("  skip  {} ({})".format(label, e))
            continue
        except Exception:
            failed += 1
            print("  FAIL  {}".format(label))
            print("".join("        " + l
                          for l in traceback.format_exc().splitlines(True)))
            continue
        print("  ok    {}{}".format(label,
                                    "" if result is None else " " + str(result)))
    print("  -- {} checks, {} failed, {} skipped".format(
        len(checks), failed, skipped))
    return 1 if failed else 0


class SkipCheck(Exception):
    """Not applicable in this environment. Never a silent pass."""


def needs_parser():
    if not parser_available():
        raise SkipCheck("no YAML parser installed")
