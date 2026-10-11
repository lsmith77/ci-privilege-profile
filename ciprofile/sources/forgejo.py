#!/usr/bin/env python3
"""Forgejo and Gitea, over the v1 API. Read-only.

    FORGE_URL=https://forge.example.org FORGE_TOKEN=... \
        python3 -m ciprofile --source forgejo

A token with repository *read* scope is enough, which is the point: the
credential can run unattended, and it is deliberately not an administrative
one. For a wholly public instance no token is needed at all.

EMPTINESS: THE FORGE SAYS SO ITSELF
-----------------------------------
`/repos/search` carries an `empty` boolean per repository, so the flag rides
along on the same listing the candidates came from and costs no second request
against a host that is often CPU-capped. It is kept exactly as answered, None
included: a repository listed without the flag is "the instance did not say",
and reading that as "not empty" would invent the answer being asked for.

WHERE PIPELINES LIVE, AND ONE DIVERGENCE FROM FORGEJO'S OWN RULE
----------------------------------------------------------------
`.forgejo/workflows`, `.gitea/workflows`, `.github/workflows`. The sweep takes
the first of those that holds workflow *files*, which is not Forgejo's rule.
Forgejo resolves on the directory: with a `.forgejo/workflows` present it reads
that and never falls back, so an empty one means the repository runs nothing.
Here an empty `.forgejo/workflows` falls through to `.github/workflows`,
deliberately, because for a corpus of repositories mirrored or migrated from
elsewhere the useful reading is the project's real CI, not what this instance
would schedule for a stub directory a migration left behind. The divergence is
in sweep.py, which is shared by every adapter.
"""
import base64
import os

from .base import (TRANSIENT, Entry, Fetcher, Refusal, Source, classify_status,
                   pace_from_env, repo as make_repo)

# Half a second. This is an instance you operate and can watch, which is the
# whole argument for it being sharper than the GitLab floor. A contents
# listing is light, but a sweep makes several requests per repository with CI.
PACE_FLOOR = 0.5
PAGE = 50


class ForgejoSource(Source):
    name = "forgejo"
    PACE_FLOOR = PACE_FLOOR
    # Two is the ceiling, and only because the host is yours. Pacing is per
    # worker, so two workers at the same pacing is twice the request rate.
    WORKER_CEILING = 2
    limitations = [
        "A repository the instance did not flag as empty, and whose root "
        "listing did not answer, is recorded as unknown rather than as having "
        "no pipeline.",
    ]

    def __init__(self, url=None, token=None, pace=None):
        url = url or os.environ.get("FORGE_URL") or ""
        if not url:
            raise Refusal(
                "set FORGE_URL to the Forgejo or Gitea instance to read, e.g. "
                "FORGE_URL=https://forge.example.org")
        token = token or os.environ.get("FORGE_TOKEN") or ""
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "token " + token
        self.authenticated = bool(token)
        self.http = Fetcher(url + "/api/v1",
                            pace if pace is not None
                            else pace_from_env("FORGE_PACE_SECONDS",
                                               PACE_FLOOR),
                            PACE_FLOOR, headers, timeout=120)
        self._empty = {}

    # ---- enumeration

    def candidates(self, limit=0):
        """Every repository the instance serves, as it spells them.

        The instance itself is the corpus, which is the only baseline that
        survives a stateless run: comparing against a file written by a
        previous run works on a populated laptop and silently covers nothing in
        a fresh container.

        A restart from page one on failure, not a resume: a listing half-read
        across an outage is two different answers stitched together.
        """
        out, page = [], 1
        while True:
            status, body, _ = self.http.get(
                "/repos/search", {"limit": PAGE, "page": page})
            if status != 200 or not isinstance(body, dict) \
                    or "data" not in body:
                raise Refusal(
                    "could not list the instance's repositories (HTTP "
                    "{}). Refusing rather than classifying whatever part of "
                    "the corpus answered: a distribution over an unannounced "
                    "subset is worse than none.".format(status))
            for r in body["data"]:
                full = r.get("full_name") or ""
                owner, _, name = full.partition("/")
                # `empty` is kept as answered, None included.
                self._empty[full.lower()] = r.get("empty")
                out.append(make_repo(full, owner, name,
                                     ref=r.get("default_branch"),
                                     meta={"empty": r.get("empty"),
                                           "size_kb": r.get("size") or 0}))
            if len(body["data"]) < PAGE:
                break
            page += 1
        return out[:limit] if limit else out

    # ---- reading

    def tree(self, repo, path=""):
        """The contents API, patient about 5xx.

        The status that comes back on failure is the one the last attempt
        actually saw, not a placeholder: it is what lands in the unknown
        reason, and a reason that cannot name the status cannot tell an outage
        from a revoked token.
        """
        where = "/" + path.strip("/") if path else ""
        status = 0
        for _ in range(3):
            status, body, _ = self.http.get(
                "/repos/{}/{}/contents{}".format(repo.owner, repo.name, where))
            if status == 200 and isinstance(body, list):
                return 200, [Entry(e.get("name", ""),
                                   "dir" if e.get("type") == "dir" else "file")
                             for e in body], False
            if classify_status(status) == TRANSIENT:
                continue
            return status, None, False
        return status, None, False

    def file_text(self, repo, path):
        status, body, _ = self.http.get(
            "/repos/{}/{}/contents/{}".format(repo.owner, repo.name, path))
        if status != 200 or not isinstance(body, dict):
            return status, None
        try:
            return 200, base64.b64decode(body.get("content") or "").decode()
        except (ValueError, UnicodeDecodeError):
            # A file that is there but unreadable is not an empty file.
            # Reported as a non-200 so it takes the "could not ask" path.
            return 599, None

    def is_empty(self, repo):
        """The instance's own `empty` flag, exactly as it answered.

        A key is absent where this repository did not come from this adapter's
        own listing, and a value is None where the instance listed it without
        the flag. Neither is "not empty".
        """
        if repo.key.lower() in self._empty:
            return self._empty[repo.key.lower()]
        return repo.meta.get("empty")
