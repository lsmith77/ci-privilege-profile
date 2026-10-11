#!/usr/bin/env python3
"""GitHub, over the REST API. Read-only.

    GITHUB_TOKEN=... python3 -m ciprofile --source github --owner some-org
    GITHUB_TOKEN=... python3 -m ciprofile --source github --repos list.txt

A token is not strictly required for public repositories but is strongly
advised: unauthenticated the limit is 60 requests an hour, which is not a
corpus. No scopes are needed (every repository read here is public), and a
fine-grained token with public read access is the right credential. It is never
sent anywhere but api.github.com.

ENUMERATION: GITHUB HAS NO CORPUS OF ITS OWN
--------------------------------------------
Unlike a self-hosted forge there is no "every repository here" listing, so the
corpus has to be named:

  --owner ORG     every repository of an organisation or user, paginated
  --repos FILE    one `owner/name` per line, which is how a corpus defined
                  somewhere else (a registry, a published index, another
                  tool's output) is fed in without this adapter having to know
                  what defined it

Forks and archived repositories are reported in the metadata rather than
filtered, because whether they belong in a corpus is the corpus's question and
not this adapter's. One filter is applied: a repository whose name makes it an
organisation *profile* repository rather than software is excluded from the
corpus, for the measured reason in EXPERIMENTS.md, "Excluding organisation
profile repositories": in a first sample of 25 by name, 17 were such
repositories, which drove `no-pipeline` to 20 of 25.

EMPTINESS: GITHUB SAYS SO IN THE 404 BODY
-----------------------------------------
There is no `empty` field on the repository object. What GitHub does expose is
a distinct message on the contents endpoint for a repository with no commits:
the body of that 404 says the repository is empty, where a 404 for a missing
path does not. So the adapter remembers the last 404 body it saw per repository
and reads emptiness off that message, and answers None when the message is
anything else.

`size` is recorded in the metadata and deliberately NOT used to decide: it is
rounded to kilobytes, so a repository holding one small file can report 0, and
reading that as empty would count real projects as doing no CI. Unknown costs a
repository its place in the distribution; a wrong "empty" costs the figure
people quote.

THE RATE BUDGET IS READ, NOT GUESSED
------------------------------------
Every response carries `X-RateLimit-Remaining`. Below RATE_FLOOR the adapter
refuses rather than spending the last of a budget that belongs to whoever owns
the token, and the sweep writes what it has and marks it partial.
"""
import os

from .base import (TRANSIENT, Entry, Fetcher, Refusal, Source, classify_status,
                   pace_from_env, repo as make_repo)

# A second, for the GitLab adapter's reason: this is somebody else's platform.
# The limit is documented here and the budget is readable, which is why this
# adapter can also stop on the budget rather than only pace against it. But
# the floor stays where reading another platform puts it.
PACE_FLOOR = 1.0
PER_PAGE = 100
# Stop with this many requests still in hand, so a run ends by writing its
# results rather than by being refused mid-corpus.
RATE_FLOOR = int(os.environ.get("GITHUB_RATE_FLOOR", "100"))
# Repository names that are a profile or metadata repository rather than
# software. `.github` is the one that matters: GitHub reads organisation-level
# issue templates, funding files and workflow defaults from it, every
# organisation that has one has it under the same name, and it sorts early in
# any name-ordered listing.
PROFILE_REPO_NAMES = {".github", ".gitlab", ".forgejo", ".gitea"}


class GitHubSource(Source):
    name = "github"
    PACE_FLOOR = PACE_FLOOR
    # None, for the GitLab adapter's reason.
    WORKER_CEILING = 1
    limitations = [
        "The corpus is whatever was named with --owner or --repos. This "
        "adapter cannot enumerate GitHub, so no figure from it describes "
        "anything wider than the list it was given.",
        "Emptiness is read off the message in GitHub's own 404 on the "
        "contents endpoint. A repository whose 404 says anything else is "
        "recorded as unknown rather than as having no pipeline, so a genuinely "
        "empty repository can leave the distribution instead of counting as "
        "no-pipeline.",
        "Forks and archived repositories are reported, not filtered: whether "
        "they belong in the corpus is the corpus's question. Organisation "
        "profile repositories ARE excluded, because they hold no software and "
        "sort early in a name-ordered listing.",
    ]

    def __init__(self, owners=(), repos_file=None, token=None, pace=None):
        token = token or os.environ.get("GITHUB_TOKEN") \
            or os.environ.get("GH_TOKEN") or ""
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = "Bearer " + token
        self.authenticated = bool(token)
        self.http = Fetcher("https://api.github.com",
                            pace if pace is not None
                            else pace_from_env("GITHUB_PACE_SECONDS",
                                               PACE_FLOOR),
                            PACE_FLOOR, headers)
        self.owners = [o for o in owners if o]
        self.repos_file = repos_file
        self.excluded = []
        self._empty_message = {}

    def _remaining(self):
        raw = self.http.last_rate_headers
        for key, value in raw.items():
            if key.lower() == "x-ratelimit-remaining":
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _check_budget(self):
        left = self._remaining()
        if left is not None and left < RATE_FLOOR:
            raise Refusal(
                "{} requests left on this token's hourly budget, below the "
                "floor of {}. Stopping with results written rather than "
                "spending the last of somebody's budget."
                .format(left, RATE_FLOOR))

    # ---- enumeration

    def candidates(self, limit=0):
        if not self.owners and not self.repos_file:
            raise Refusal(
                "--source github needs a corpus: --owner ORG (repeatable) or "
                "--repos FILE with one owner/name per line. GitHub cannot be "
                "enumerated, so there is no default corpus and no sensible "
                "guess at one.")
        out = []
        for owner in self.owners:
            out += self._owner_repos(owner)
        if self.repos_file:
            out += self._listed_repos(self.repos_file)
        seen, uniq = set(), []
        for r in out:
            if r.key.lower() in seen:
                continue
            seen.add(r.key.lower())
            if r.name in PROFILE_REPO_NAMES:
                # Excluded from the denominator, and named in the output: a
                # silent exclusion is a figure nobody can check.
                self.excluded.append({"repo": r.key,
                                      "reason": "organisation profile "
                                                "repository, holds no "
                                                "software"})
                continue
            uniq.append(r)
        if not uniq:
            raise Refusal("no repositories to classify after exclusions")
        return uniq[:limit] if limit else uniq

    def _owner_repos(self, owner):
        """Every repository of an organisation, or of a user.

        Tries the organisation endpoint and falls back to the user one on a
        404: which of the two an account is cannot be read off its name, and
        guessing wrong would report an account as having no repositories.
        """
        for path in ("/orgs/{}/repos".format(owner),
                     "/users/{}/repos".format(owner)):
            out, page = [], 1
            while True:
                self._check_budget()
                status, body, _ = self.http.get(
                    path, {"per_page": PER_PAGE, "page": page,
                           "type": "public", "sort": "full_name"})
                if status == 404 and page == 1:
                    break                      # try the other endpoint
                if status != 200 or not isinstance(body, list):
                    raise Refusal(
                        "could not list {} (HTTP {}): refusing rather than "
                        "classifying part of the corpus".format(owner, status))
                for r in body:
                    out.append(self._repo_from(r))
                if len(body) < PER_PAGE:
                    return out
                page += 1
        raise Refusal("no such organisation or user: {}".format(owner))

    def _repo_from(self, r):
        return make_repo(r.get("full_name") or "",
                         ref=r.get("default_branch"),
                         meta={"size_kb": r.get("size"),
                               "fork": bool(r.get("fork")),
                               "archived": bool(r.get("archived")),
                               "default_branch": r.get("default_branch")})

    def _listed_repos(self, path):
        """`owner/name` per line. Blank lines and `#` comments ignored."""
        out = []
        with open(path) as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                if line.count("/") != 1:
                    raise Refusal(
                        "{}: {!r} is not owner/name".format(path, line))
                out.append(make_repo(line))
        if not out:
            raise Refusal("{} names no repositories".format(path))
        return out

    # ---- reading

    def tree(self, repo, path=""):
        self._check_budget()
        where = "/" + path.strip("/") if path else ""
        status, body = 0, None
        for _ in range(3):
            status, body, _ = self.http.get(
                "/repos/{}/{}/contents{}".format(repo.owner, repo.name, where),
                {"ref": repo.ref} if repo.ref else None)
            if status == 200 and isinstance(body, list):
                return 200, [Entry(e.get("name", ""),
                                   "dir" if e.get("type") == "dir" else "file")
                             for e in body], False
            if classify_status(status) == TRANSIENT:
                continue
            break
        if status == 404 and isinstance(body, str) and not path:
            # The one place GitHub says a repository is empty. Remembered
            # rather than acted on here: is_empty() is where it is read.
            self._empty_message[repo.key.lower()] = body
        return status, None, False

    def file_text(self, repo, path):
        self._check_budget()
        # The raw media type, so the body is the file and not base64 in JSON.
        status, body, _ = self.http.get(
            "/repos/{}/{}/contents/{}".format(repo.owner, repo.name, path),
            {"ref": repo.ref} if repo.ref else None, text=True,
            headers={"Accept": "application/vnd.github.raw+json"})
        return (status, body) if status == 200 else (status, None)

    def is_empty(self, repo):
        """True only where GitHub's own 404 said the repository is empty.

        `size` is not consulted; see the module docstring for why a rounded
        kilobyte figure must not decide this.
        """
        body = self._empty_message.get(repo.key.lower())
        if body is None:
            return None
        return True if "repository is empty" in body.lower() else None
