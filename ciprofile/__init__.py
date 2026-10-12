#!/usr/bin/env python3
"""What privilege a CI pipeline would need in order to run.

The question: for a corpus of repositories, what would a host have to grant
before each project's pipeline ran at all (secrets, outward writes, forge-API
access, special runners), and could a contributor run the same checks on their
own infrastructure?

Read README.md's limitations section before quoting anything this produces, and
EXPERIMENTS.md for how the current design was arrived at and which other
approaches are worth trying.

    structure.py   where pipelines live; cutting their text into units
    rules.py       the signal tables, and what a privilege is for
    classify.py    the two scopes, the ladder, the derived figures
    sweep.py       discovery, and what a failure means
    cache.py       the evidence cache, and refusing to misread one
    report.py      the profile JSON and the printed summary
    fixtures.py    the offline corpus and its expectation table
    differential.py  running the pipeline with nothing granted, and what a
                   failure is allowed to be read as
    ci_activity.py whether the declared pipeline ever ran upstream, which is
                   also the control for the above
    sources/       one adapter per forge, behind one interface
"""
