#!/usr/bin/env python3
"""The local source: a directory of checkouts, or an evidence cache. No network.

    python3 -m ciprofile --source local --root ./corpus
    python3 -m ciprofile --source local --root ./ci_cache.json

This adapter is why the tool is testable by anybody. The fixture suite runs
through it, so every rule in rules.py can be exercised with no credential, no
host and no network. And the test suite takes the socket layer away while it
does, so a stub that quietly fell through to a forge would fail rather than
spend somebody's rate budget from a test run.

TWO MODES, ONE INTERFACE
------------------------
  - A DIRECTORY, which is a corpus of checkouts, or a tree of synthetic
    repositories like `fixtures/ci/`. Each repository is read off the disk
    exactly as a forge adapter would read it off an API: the *path* is what
    decides which grammar a file is read with, so the fixtures are laid out as
    repositories rather than as a flat pile of YAML.
  - AN EVIDENCE CACHE, the JSON a sweep writes of everything it fetched. This
    is what makes re-analysis free: a full sweep of a sizeable corpus is an
    hour and a half of paced requests, and before the cache existed every
    change to a rule cost another one. See EXPERIMENTS.md, "Caching the
    fetched text, and doing it too late", including the lesson that it should
    have been built first.

    A cached run re-runs the RULES over stored inputs; it never replays stored
    conclusions. The emptiness reading in particular is re-derived from the
    stored status and the stored flag, because that rule is among the most
    worth changing and a cache that could only repeat last week's answer to it
    would be no use for changing it.

    Everything derived from a cache says, where it cannot be missed, that it
    describes the corpus as of the fetch date and is not a fresh measurement.
    cache.py carries that banner; this adapter carries the data.

DEPTH IS DETECTED, NOT CONFIGURED
---------------------------------
A corpus on disk is written either way (`<root>/<name>` or
`<root>/<owner>/<name>`), so each top-level directory is judged on its own: one
that directly holds files or a pipeline directory is a repository, and one that
holds nothing but directories is an owner, whose children are the
repositories. Deterministic, and it means neither layout needs a flag.
"""
import json
import os

from .base import Entry, Refusal, Source, repo as make_repo
from ..structure import GITLAB_FILE, WORKFLOW_DIRS

# A directory whose presence makes its parent a repository rather than an owner.
REPO_MARKERS = {".git"} | {d.split("/", 1)[0] for d in WORKFLOW_DIRS}


class LocalSource(Source):
    name = "local"
    PACE_FLOOR = 0.0
    WORKER_CEILING = 1
    offline = True

    def __init__(self, root):
        if not root:
            raise Refusal("--source local needs --root: a directory of "
                          "repositories, or an evidence cache JSON")
        self.root = root
        self.cache = None
        if os.path.isfile(root):
            self.mode = "cache"
            self.cache = self._read_cache(root)
        elif os.path.isdir(root):
            self.mode = "directory"
        else:
            raise Refusal("no such path: {}".format(root))
        self.limitations = (
            ["Re-analysed from an evidence cache: the figures describe the "
             "corpus as it stood on the fetch date recorded in the cache, not "
             "as it stands now, and nothing here was re-read from any host."]
            if self.mode == "cache" else
            ["Read from a local directory, so the figures describe whatever "
             "that directory holds. A checkout is a snapshot of one branch."])

    def describe(self):
        out = Source.describe(self)
        out["mode"] = self.mode
        out["root"] = self.root
        if self.cache:
            out["cache_fetched"] = [self.cache.get("fetched_oldest"),
                                    self.cache.get("fetched_newest")]
            out["cache_partial"] = bool(self.cache.get("partial"))
        return out

    # ---- cache mode

    @staticmethod
    def _read_cache(path):
        """The cache, or a refusal saying why it cannot be used.

        Every failure here refuses. The alternative to refusing is a
        distribution over an unannounced subset of the corpus, which is the one
        output worth less than no output at all: nothing about it looks wrong.
        """
        from ..cache import read_cache
        return read_cache(path)

    def cached(self, repo):
        """(root_status, files, other_ci, reason) from the cache, or None.

        The INPUTS, not a conclusion: the sweep re-applies its own emptiness
        rule to the status and the flag. See the module docstring.
        """
        if self.mode != "cache":
            return None
        entry = self.cache["repos"].get(repo.key) or {}
        status = entry.get("root_status")
        if status != 200:
            return status, None, None, None
        if entry.get("reason"):
            return status, None, None, entry["reason"]
        return status, entry.get("files") or {}, entry.get("other_ci") or [], None

    # ---- enumeration

    def candidates(self, limit=0):
        if self.mode == "cache":
            out = [make_repo(key, meta={"empty": entry.get("empty")})
                   for key, entry in sorted(self.cache["repos"].items())]
        else:
            out = [make_repo(key, meta={"path": path})
                   for key, path in self._repo_dirs()]
        if not out:
            raise Refusal("{} holds no repositories".format(self.root))
        return out[:limit] if limit else out

    def _repo_dirs(self):
        """[(key, path)]: see DEPTH IS DETECTED, NOT CONFIGURED."""
        out = []
        for top in sorted(os.listdir(self.root)):
            if top.startswith("."):
                continue
            path = os.path.join(self.root, top)
            if not os.path.isdir(path):
                continue
            children = sorted(os.listdir(path))
            looks_like_repo = any(
                c in REPO_MARKERS or c == GITLAB_FILE
                or os.path.isfile(os.path.join(path, c)) for c in children)
            if looks_like_repo or not children:
                out.append((top, path))
                continue
            for sub in children:
                subpath = os.path.join(path, sub)
                if os.path.isdir(subpath):
                    out.append((top + "/" + sub, subpath))
        return out

    # ---- reading

    def _dir(self, repo, path):
        base = repo.meta.get("path") or os.path.join(self.root, repo.key)
        return os.path.join(base, path) if path else base

    def tree(self, repo, path=""):
        where = self._dir(repo, path)
        if not os.path.isdir(where):
            return 404, None, False
        entries = []
        for name in sorted(os.listdir(where)):
            full = os.path.join(where, name)
            entries.append(Entry(name, "dir" if os.path.isdir(full) else "file"))
        return 200, entries, False

    def file_text(self, repo, path):
        full = self._dir(repo, path)
        if not os.path.isfile(full):
            return 404, None
        try:
            with open(full) as fh:
                return 200, fh.read()
        except (OSError, UnicodeDecodeError):
            # A file that is there and unreadable is not an empty file, and the
            # status is what sends it down the "could not read" path.
            return 599, None

    def is_empty(self, repo):
        """True where the checkout holds no file at all; None where it is gone.

        The local analogue of the forge flag, and it decides in the same
        direction: a directory holding nothing is empty, a directory that is
        not there is unknown rather than empty.
        """
        if self.mode == "cache":
            return (self.cache["repos"].get(repo.key) or {}).get("empty")
        base = self._dir(repo, "")
        if not os.path.isdir(base):
            return None
        for _dirpath, _dirs, names in os.walk(base):
            if names:
                return False
        return True
