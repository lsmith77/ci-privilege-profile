#!/usr/bin/env python3
"""Discovery and the sweep: which files to read, and what a failure means.

This is the one piece of fetching logic shared by every source. It knows where
pipelines live and nothing about any forge's API; that is the adapters' half,
behind the interface in sources/base.py.

UNDER-CLAIM ON FAILURE
----------------------
A repository whose files could not be read is recorded in `unknown` with the
reason, left out of the profile, and excluded from every distribution. It is
never counted as `no-pipeline`: that would turn every transient 503 into
evidence of an absent pipeline and overstate the one number most likely to be
quoted.

The single exception is a repository the source says is empty. A 404 on the
root listing is ambiguous on its own, so the status code does not decide it:
the adapter is asked, and the three answers are read as empty_verdict() reads
them. See WHY `is_empty` IS PART OF THE INTERFACE in sources/base.py.

WHERE PIPELINES LIVE
--------------------
`.forgejo/workflows/`, `.gitea/workflows/` and `.github/workflows/` (the first
of those that holds workflow files), plus `.gitlab-ci.yml` at the root. Nothing
else is read, and that is the biggest single caveat on `no-pipeline`: a
repository driven by Travis, Jenkins, Drone, CircleCI, Woodpecker or Azure
Pipelines has a pipeline that none of these locations holds. Those root markers
are recorded per repository as `other_ci` and counted separately in the
summary, so `no-pipeline` is never read as "this project does not do CI".
"""
import concurrent.futures
import threading

from .classify import classify
from .structure import GITLAB_FILE, OTHER_CI, WORKFLOW_DIRS, WORKFLOW_EXT

# Above this, the workflow directory is not read at all and the repository is
# recorded as unknown. Reading a prefix instead would mean classifying from
# part of the evidence, and the part left out is exactly where the highest
# signal might be.
MAX_WORKFLOW_FILES = 40
# Checkpoint interval, so an interrupted sweep is not lost.
SAVE_EVERY = 25


def empty_verdict(status, empty):
    """How a root listing that did not answer 200 is read.

    (files, other_ci, reason). A reason means unknown.

    Its own function because a cached re-analysis re-runs this rule off the
    cached status and the cached flag rather than replaying a stored
    conclusion. It is among the rules most worth changing (it decides whether
    a repository whose default branch is unborn is counted as a project that
    does no CI), and a cache that could only repeat the previous answer to it
    would be no use for changing it.
    """
    if status != 404:
        return None, None, "root listing HTTP {}".format(status)
    # Asked of the repository's own state, not inferred from the status: a 404
    # here is what an empty repository and one with an unborn or missing
    # default branch both answer.
    if empty:
        return {}, [], None
    if empty is None:
        return None, None, ("root listing HTTP 404 and the source did not say "
                            "whether the repository is empty")
    return None, None, ("root listing HTTP 404 but the source reports the "
                        "repository as not empty: an unborn or missing "
                        "default branch reads this way")


def fetch_repo(source, repo):
    """({path: text}, other_ci, None, root status), or (None, None, reason, s).

    A reason means unknown: recorded as such, left out of the distribution.
    The root status comes back with the answer because the evidence cache
    stores it: the emptiness rule is re-derived from it later, so it is an
    input and not a detail of this call.
    """
    status, root, truncated = source.tree(repo)
    if status != 200 or root is None:
        if truncated:
            return None, None, ("root listing longer than the page cap, so "
                                "the absence of a pipeline file cannot be "
                                "read off it"), status
        files, other, reason = empty_verdict(status, source.is_empty(repo))
        return files, other, reason, status

    names = {e.name: e.type for e in root}
    other = [n for n in names if n.lower() in OTHER_CI]
    files, wanted = {}, []

    for d in WORKFLOW_DIRS:
        top = d.split("/", 1)[0]
        if names.get(top) != "dir":
            continue
        dir_status, entries, truncated = source.tree(repo, d)
        if dir_status == 404:
            continue          # the top-level dir exists, workflows/ does not
        if dir_status != 200 or entries is None:
            return None, None, "{} listing HTTP {}{}".format(
                d, dir_status, ", truncated" if truncated else ""), status
        hits = [e.name for e in entries
                if e.type == "file" and e.name.lower().endswith(WORKFLOW_EXT)]
        if len(hits) > MAX_WORKFLOW_FILES:
            return None, None, "{} holds {} files, over the {} cap".format(
                d, len(hits), MAX_WORKFLOW_FILES), status
        wanted += ["{}/{}".format(d, h) for h in hits]
        if hits:
            # The first of the three that holds workflow *files* wins, which is
            # not Forgejo's own rule; see the divergence in
            # sources/forgejo.py. Where two locations both hold files only the
            # first is read, which is the one case where this under-claims. It
            # is accepted: the shapes that produce it are a forge migration in
            # progress and a deliberate per-forge pipeline, both of which are
            # one project expressing one pipeline twice rather than two sets of
            # requirements, so the evidence left out is near-duplicate.
            break

    if names.get(GITLAB_FILE) == "file":
        wanted.append(GITLAB_FILE)

    for path in wanted:
        file_status, text = source.file_text(repo, path)
        if file_status != 200 or text is None:
            # A file that is there and unreadable could be the one carrying the
            # highest signal, so the repository goes to unknown rather than be
            # classified from the rest.
            return None, None, "{} HTTP {}".format(path, file_status), status
        files[path] = text
    return files, other, None, status


def _one(source, repo, recorder):
    """(profile, None) or (None, reason), recording the evidence on the way.

    Where the source has the evidence already (a cache), the stored inputs
    are used and the rules are re-run over them. Never the stored conclusions.
    """
    cached = getattr(source, "cached", None)
    if cached is not None:
        got = cached(repo)
        if got is not None:
            status, files, other, reason = got
            if reason:
                return None, reason
            if status != 200:
                files, other, reason = empty_verdict(status,
                                                     source.is_empty(repo))
                if reason:
                    return None, reason
            return classify(files, other), None
    files, other, reason, status = fetch_repo(source, repo)
    if recorder is not None:
        recorder.record(repo.key, status, source.is_empty(repo), files, other,
                        reason)
    if reason:
        return None, reason
    return classify(files, other), None


def sweep(source, repos, workers=1, recorder=None, checkpoint=None,
          log=print):
    """({key: profile}, {key: reason}).

    Paced inside the worker, so the worker count is the only thing that
    changes the load: two workers at the same pacing is twice the request rate,
    not an unbounded burst. The ceiling is the adapter's, because what is
    acceptable against a host you operate is not what is acceptable against
    one you do not.
    """
    workers = max(1, min(int(workers or 1), source.WORKER_CEILING))
    profiles, unknown = {}, {}
    lock = threading.Lock()
    state = {"done": 0}

    def run(repo):
        prof, reason = _one(source, repo, recorder)
        with lock:
            if reason:
                unknown[repo.key] = reason
            else:
                profiles[repo.key] = prof
            state["done"] += 1
            if checkpoint and state["done"] % SAVE_EVERY == 0:
                checkpoint(profiles, unknown)
                log("  [{}/{}] ...".format(state["done"], len(repos)))

    if workers == 1:
        for r in repos:
            run(r)
    else:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers) as pool:
            list(pool.map(run, repos))
    return profiles, unknown
