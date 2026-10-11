#!/usr/bin/env python3
"""The four sources, behind one interface. See base.py for the interface.

    forgejo   Forgejo or Gitea, v1 API, token with read scope
    gitlab    GitLab, v4 API, unauthenticated, a stratified sample
    github    GitHub, REST API, a corpus named with --owner or --repos
    local     a directory of checkouts, or an evidence cache. No network.

Nothing above this package knows which one is in use. A new forge is a new
file here and no change anywhere else; if that stops being true, the seam has
been crossed and the fix belongs here rather than in the classifier.
"""
from .base import (ABSENT, OK, REFUSED, TRANSIENT, Entry, Refusal, Repo,
                   Source, classify_status, repo)

NAMES = ("forgejo", "gitlab", "github", "local")


def build(name, **kw):
    """One source by name. Imported lazily so no adapter is a prerequisite."""
    if name == "forgejo":
        from .forgejo import ForgejoSource
        return ForgejoSource(url=kw.get("url"), token=kw.get("token"),
                             pace=kw.get("pace"))
    if name == "gitlab":
        from .gitlab import GitLabSource
        return GitLabSource(url=kw.get("url"), pace=kw.get("pace"),
                            sample=kw.get("sample"))
    if name == "github":
        from .github import GitHubSource
        return GitHubSource(owners=kw.get("owners") or (),
                            repos_file=kw.get("repos_file"),
                            token=kw.get("token"), pace=kw.get("pace"))
    if name == "local":
        from .local import LocalSource
        return LocalSource(root=kw.get("root"))
    raise Refusal("unknown source {!r}: one of {}".format(
        name, ", ".join(NAMES)))


__all__ = ["ABSENT", "OK", "REFUSED", "TRANSIENT", "Entry", "NAMES", "Refusal",
           "Repo", "Source", "build", "classify_status", "repo"]
