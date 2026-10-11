#!/usr/bin/env python3
"""Command line.

    python3 -m ciprofile --fixtures
    python3 -m ciprofile --source local   --root ./corpus
    python3 -m ciprofile --source local   --root ./data/ci_cache.json
    python3 -m ciprofile --source forgejo
    python3 -m ciprofile --source gitlab  --sample 20
    python3 -m ciprofile --source github  --owner some-org

One mode is deliberately awkward: `--source gitlab` has no default sample size,
because no spelling of it should start reading somebody else's platform without
a person having said how much of it to read. The source refuses rather than
defaulting.

`--limit` writes a profile marked partial, and the reason is in the file: a
prefix of a listing is not a sample, and in a name-ordered listing it is not
close to one. See EXPERIMENTS.md, "Excluding organisation profile
repositories".
"""
import argparse
import json
import os
import sys

from . import cache as cachemod
from . import fixtures, report, sources
from .sweep import sweep


def build_parser():
    p = argparse.ArgumentParser(
        prog="python3 -m ciprofile",
        description="What privilege a CI pipeline would need in order to run, "
                    "and whether a contributor could run it on their own "
                    "infrastructure. Read-only, paced, and it under-claims on "
                    "failure.")
    p.add_argument("--fixtures", action="store_true",
                   help="run the offline fixture corpus and exit")
    p.add_argument("--source", choices=sources.NAMES,
                   help="which forge, or `local` for a directory or a cache")
    p.add_argument("--url", help="instance URL (else FORGE_URL / GITLAB_URL)")
    p.add_argument("--token", help="read-scoped token (else the environment)")
    p.add_argument("--owner", action="append", default=[],
                   help="github: an organisation or user to enumerate, "
                        "repeatable")
    p.add_argument("--repos", help="github: a file of owner/name per line")
    p.add_argument("--root", help="local: a directory of repositories, or an "
                                  "evidence cache JSON")
    p.add_argument("--sample", type=int,
                   help="gitlab: how many projects to sample. Required, with "
                        "no default")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after N repositories. The profile is then "
                        "marked partial, because a prefix is not a sample")
    p.add_argument("--workers", type=int, default=1,
                   help="clamped to the source's own ceiling; pacing is per "
                        "worker, so this is the request rate")
    p.add_argument("--out", default="data",
                   help="directory for the profile and the evidence cache")
    p.add_argument("--no-cache", action="store_true",
                   help="do not write the evidence cache. Build it first "
                        "rather than last; see EXPERIMENTS.md")
    p.add_argument("--compare",
                   help="a previous profile to diff this run against "
                        "(default: the one in --out)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.fixtures:
        return fixtures.check()
    if not args.source:
        build_parser().print_usage()
        return "pick a --source, or --fixtures for the offline self-test"

    cached_run = bool(args.source == "local" and args.root
                      and os.path.isfile(args.root))
    if cached_run:
        # Before the cache is even opened, and before any import that might
        # reach out: the mode's whole claim is that re-analysis costs nothing.
        cachemod.forbid_network("a cached re-analysis reached the network")

    try:
        source = sources.build(
            args.source, url=args.url, token=args.token, root=args.root,
            owners=args.owner, repos_file=args.repos, sample=args.sample)
        repos = source.candidates(limit=args.limit)
    except sources.Refusal as e:
        return str(e)

    os.makedirs(args.out, exist_ok=True)
    cache = source.cache if cached_run else None
    out_path = os.path.join(
        args.out, report.FROM_CACHE_NAME if cached_run
        else report.PROFILE_NAME)
    cache_path = os.path.join(args.out, report.CACHE_NAME)
    before = report.previous_profile(
        args.compare or os.path.join(args.out, report.PROFILE_NAME))

    recorder = None
    if not cached_run and not source.offline and not args.no_cache:
        recorder = cachemod.Recorder(source.describe())

    limited = bool(args.limit)
    print("classifying {} repositories from {} at {}s pacing, {} worker(s){}"
          .format(len(repos), source.name,
                  source.describe().get("pace_seconds"),
                  max(1, min(args.workers, source.WORKER_CEILING)),
                  "; --limit in force, the profile is partial" if limited
                  else ""))

    def checkpoint(profiles, unknown):
        report.write(out_path, profiles, unknown, source, partial=True,
                     cache=cache)
        if recorder is not None:
            recorder.write(cache_path, partial=True,
                           reason="interrupted mid-sweep", log=lambda _m: None)

    try:
        profiles, unknown = sweep(source, repos, workers=args.workers,
                                  recorder=recorder,
                                  checkpoint=checkpoint if recorder else None)
    except sources.Refusal as e:
        return str(e)

    extra = {}
    if getattr(source, "selection", None):
        extra["selection"] = source.selection
    if getattr(source, "excluded", None):
        extra["excluded_from_corpus"] = source.excluded
    report.write(out_path, profiles, unknown, source, limited=limited,
                 cache=cache, extra=extra)
    if recorder is not None:
        recorder.write(cache_path, covered=set(profiles) | set(unknown),
                       partial=limited,
                       reason="a limit was in force" if limited else "")
    report.report(before, profiles, unknown, cache=cache, source=source)
    print("\nwrote " + out_path)
    if cached_run:
        print("the sweep's own {} is untouched".format(report.PROFILE_NAME))
    return 0


if __name__ == "__main__":
    sys.exit(main())
