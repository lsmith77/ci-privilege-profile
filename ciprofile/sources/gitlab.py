#!/usr/bin/env python3
"""GitLab, over the v4 API, unauthenticated. Read-only.

    GITLAB_URL=https://gitlab.example.org \
        python3 -m ciprofile --source gitlab --sample 20

Deliberately not the Forgejo adapter's twin. That one talks to an instance you
operate, with a credential. This one is written for reading a platform somebody
else operates, with no credential at all: there is no Authorization header
anywhere in it, by construction. A credential would also change *what is
visible*, which would make a published sample unreproducible by anyone who does
not hold the token.

PACED MORE GENTLY THAN THE FORGEJO PATH, AND WHY
------------------------------------------------
Another organisation's production platform. Its rate limits are not documented
to you and the headers it returns need not be self-consistent: one
unauthenticated listing came back with `RateLimit-Limit: 60`,
`RateLimit-Observed: 1` and `RateLimit-Remaining: 1799` at once, so the real
budget cannot be read off them with any confidence. The floor is therefore a
full second, twice as gentle as the Forgejo path, and there is no concurrency
on this path whatsoever. The headers are recorded verbatim rather than acted
on, so an operator reading the output sees what the host actually said instead
of this adapter's reading of it.

A SAMPLE, STRATIFIED, AND NEVER A SWEEP BY ACCIDENT
---------------------------------------------------
`--sample N` is required with no default: no spelling of this mode starts
reading somebody else's platform without a person having said how much of it to
read. Above SAMPLE_CEILING it refuses unless ALLOW_LARGE_SAMPLE is set; the
ceiling stops the typo, not the decision.

The sample is stratified rather than taken off the head of the listing, because
a small sample chosen badly is worse than none: twenty projects from one
organisation's estate measure one team's house style and read as a reading of
the corpus. Breadth first, grouped on the TOP-LEVEL path segment (the
publishing organisation) and not on the API's `namespace`, which names only
the immediate group, one team inside one organisation.

WHAT THIS CANNOT SEE
--------------------
`ci_config_path` is invisible to an unauthenticated listing, so a project whose
CI configuration lives at a custom or external path reads here as having no CI
at all. That inflates `no-pipeline`, the figure most worth quoting, and the
error is one-directional. The only mitigation available without a credential is
to name the CI-looking files that sit beside the conventional path, which is
what `ci_elsewhere` does. `archived` is invisible too, so an archived project
cannot be filtered out.

EMPTINESS: A DOCUMENTED PROXY, AND WHAT IT REFUSES TO DECIDE
------------------------------------------------------------
`empty_repo` is not in an unauthenticated project listing, so the flag the
Forgejo adapter reads straight off its answer does not exist here. The proxy is
`default_branch`:

  - present  -> not empty. A branch exists, so there is content behind it.
                This is the direction that matters most, because it is the one
                that produces the *contradiction* reading: a 404 on the tree of
                a project that has a default branch is a failure to read, not
                an absence of content, and the repository goes to unknown.
  - absent    -> unknown, NOT empty. The listing omits the key entirely for a
                project whose repository is not readable, and such a project
                answers 403 on the tree endpoint. But 403 is equally what a
                project with the repository feature disabled answers, and the
                two causes cannot be told apart from outside. Calling that
                "empty" would count a project whose repository is merely
                private-by-feature as a project that does no CI.

So this adapter can confirm "not empty" and never confirms "empty". The cost is
that a genuinely empty GitLab project leaves the distribution as unknown
instead of being counted as `no-pipeline`; the alternative costs the figure
that gets quoted. Verifying it properly needs an authenticated listing, where
`empty_repo` and `repository_access_level` are both exposed and say which of
the two causes it is.
"""
import os
import urllib.parse

from .base import (Entry, Fetcher, Refusal, Source, pace_from_env,
                   repo as make_repo)

# One second is the floor, not the default; see the module docstring.
PACE_FLOOR = 1.0
# The intended use is about twenty projects, and the next round number up is
# still a sample rather than a sweep. The point of the ceiling is not that 26
# would be harmful; it is that a full sweep of somebody else's platform must
# take a deliberate act, and a typo cannot be one.
SAMPLE_CEILING = 25
# At most two projects per publishing organisation, filled breadth-first. Two
# rather than one because a single project per publisher cannot show whether an
# idiom is the publisher's house style or the project's.
PER_ORG = 2
# How many listing pages may be read to build the candidate pool. One page of
# 100 commonly spans twenty-odd organisations, so one page is normally the
# whole cost; the cap bounds the pathological case.
LISTING_PAGE_CAP = 5
LISTING_PER_PAGE = 100
# A directory with more entries than this is not read at all and the project is
# recorded as unreadable. Reading a prefix instead would mean deciding "there
# is no pipeline file here" from part of a listing.
TREE_PAGE_CAP = 5


def top_level_org(path_with_namespace):
    """The publishing organisation: the FIRST path segment, not `namespace`.

    Paths nest several groups deep, and the `namespace` object in the listing
    names only the immediate group, one team inside one organisation. The
    publisher is the root group, so a sample that wants to span publishers has
    to group on this.
    """
    return (path_with_namespace or "").split("/", 1)[0]


class GitLabSource(Source):
    name = "gitlab"
    PACE_FLOOR = PACE_FLOOR
    # None. Pacing is per worker, so a second worker is twice the request rate
    # against infrastructure that is not yours and whose limits you cannot
    # read. The Forgejo path's ceiling of two does not carry over.
    WORKER_CEILING = 1
    limitations = [
        "NOT A DISTRIBUTION. A sample of this size measures nothing about the "
        "corpus. It exists to validate the rule set against real GitLab CI and "
        "to surface idioms the rules miss. Any share, percentage or \"most "
        "projects\" read off it is a misreading.",
        "`ci_config_path` is invisible to an unauthenticated project listing, "
        "so a project whose CI configuration lives at a custom or external "
        "path reads here as having no CI at all. This inflates `no-pipeline`, "
        "and the error is one-directional. `ci_elsewhere` per project names "
        "the CI-looking files found in the repository root and in `.gitlab/`, "
        "which is the only mitigation available without a credential: a "
        "project listed there with no pipeline of its own is a project whose "
        "`no-pipeline` reading should not be believed. An empty "
        "`ci_elsewhere` is not evidence that there is no custom path.",
        "`archived` is invisible as well, so archived projects cannot be "
        "filtered out and may be in the sample.",
        "`empty_repo` is invisible, so emptiness is read off a proxy: a "
        "default branch means not empty, and its absence means unknown rather "
        "than empty. A genuinely empty project therefore leaves the "
        "distribution as unknown instead of counting as no-pipeline.",
        "The GitLab grammar is classified whole, with no job-level "
        "reachability, so the pull-request scope over-claims for a project "
        "whose deploy job is branch-gated.",
    ]

    def __init__(self, url=None, pace=None, sample=None, allow_large=None):
        url = url or os.environ.get("GITLAB_URL") or ""
        if not url:
            raise Refusal(
                "set GITLAB_URL to the instance to sample, e.g. "
                "GITLAB_URL=https://gitlab.example.org")
        self.authenticated = False
        # No Authorization header anywhere in this module, by construction.
        self.http = Fetcher(url + "/api/v4",
                            pace if pace is not None
                            else pace_from_env("GITLAB_PACE_SECONDS",
                                               PACE_FLOOR),
                            PACE_FLOOR, {"Accept": "application/json"})
        self.sample = sample
        self.allow_large = (os.environ.get("ALLOW_LARGE_SAMPLE", "")
                            not in ("", "0")) if allow_large is None \
            else allow_large
        # Filled by candidates(), reported in the output: the sample is
        # arguable rather than a black box.
        self.selection = {}

    def require_sample(self, sample):
        """Refuse unless the size was given explicitly and is small enough.

        Two separate refusals, because they stop two different accidents. A
        missing size stops the one that matters most: there is no default. A
        size above the ceiling stops the typo (an extra zero) and is
        overridable, because a deliberate larger read is a decision somebody is
        allowed to make, in writing, through the environment.
        """
        if not sample:
            raise Refusal(
                "--sample takes a size: how many projects to classify. There "
                "is deliberately no default: this reads a platform somebody "
                "else operates, so the size is always an explicit decision.")
        if sample > SAMPLE_CEILING and not self.allow_large:
            raise Refusal(
                "--sample {} is above the {}-project ceiling for reading "
                "somebody else's instance. Re-run with ALLOW_LARGE_SAMPLE=1 if "
                "that is deliberate.".format(sample, SAMPLE_CEILING))

    # ---- enumeration

    def _projects_page(self, page):
        """One page of public projects, newest activity first.

        The API's own default order is creation date, where the head of the
        listing is whatever was imported most recently. Last activity is the
        order a sample of the *live* corpus wants, and it is honoured
        unauthenticated.
        """
        status, body, headers = self.http.get(
            "/projects", {"per_page": LISTING_PER_PAGE, "page": page,
                          "order_by": "last_activity_at", "sort": "desc"})
        if status != 200 or not isinstance(body, list):
            return status, None, None
        nxt = headers.get("X-Next-Page") if headers else None
        try:
            nxt = int(nxt)
        except (TypeError, ValueError):
            nxt = None
        return 200, body, nxt

    def _readable(self, proj):
        """Whether the project has a repository this can read at all.

        The listing omits `default_branch` entirely for a project whose
        repository is not readable (the key is absent, not null), and such a
        project answers 403 on the tree endpoint, so it is dropped at selection
        rather than spent on. Absent and null are both taken as "no", since
        neither is a branch.
        """
        return bool(proj.get("default_branch"))

    def _select(self, candidates, sample):
        """(picked, orgs): the stratified sample and the per-organisation pool.

        Group by the top-level path segment; order the organisations by their
        own most recently active project, and each organisation's projects the
        same way; take one project per organisation in that order, then a
        second, up to PER_ORG and up to the sample size.

        The first pick is therefore the single most recently active readable
        project in the pool, which is deliberate: that is where the live idioms
        the sample exists to find actually are. Each pick records the round
        that took it.
        """
        orgs = {}
        for p in candidates:
            orgs.setdefault(top_level_org(p["path_with_namespace"]),
                            []).append(p)
        for group in orgs.values():
            group.sort(key=lambda p: p.get("last_activity_at") or "",
                       reverse=True)
        order = sorted(orgs,
                       key=lambda o: orgs[o][0].get("last_activity_at") or "",
                       reverse=True)
        picked = []
        for rnd in range(PER_ORG):
            for org in order:
                if len(picked) >= sample:
                    return picked, orgs
                group = orgs[org]
                if rnd < len(group):
                    picked.append((org, group[rnd], rnd + 1))
        return picked, orgs

    def _selectable(self, orgs, sample):
        return sum(min(PER_ORG, len(g)) for g in orgs.values()) >= sample

    def candidates(self, limit=0):
        sample = limit or self.sample
        self.require_sample(sample)
        pool, skipped, page, pages = [], [], 1, 0
        while page and pages < LISTING_PAGE_CAP:
            status, batch, nxt = self._projects_page(page)
            pages += 1
            if status != 200:
                raise Refusal(
                    "could not read the project listing (HTTP {}) on page "
                    "{}: refusing rather than sampling whatever answered"
                    .format(status, page))
            for p in batch:
                if not p.get("path_with_namespace"):
                    continue
                (pool if self._readable(p) else skipped).append(p)
            groups = {}
            for p in pool:
                groups.setdefault(
                    top_level_org(p["path_with_namespace"]), []).append(p)
            if self._selectable(groups, sample):
                break
            page = nxt
        if not pool:
            raise Refusal("no candidate projects: nothing classified")
        picked, orgs = self._select(pool, sample)
        # `skipped` is named in the output, with activity timestamps: the most
        # recently active project overall can be one of them, and an output
        # that did not say so would look like the sample had simply missed it.
        self.selection = {
            "rule": ("Public projects, ordered by last_activity_at "
                     "descending. Projects without a default_branch are "
                     "skipped: they have no readable repository. The rest are "
                     "grouped by TOP-LEVEL path segment, which is the "
                     "publishing organisation and not the API's `namespace`; "
                     "organisations are ordered by their own most recently "
                     "active project; one project is taken per organisation, "
                     "then a second, up to {} per organisation and up to the "
                     "sample size.".format(PER_ORG)),
            "sample_size_requested": sample,
            "per_organisation_cap": PER_ORG,
            "listing_pages_read": pages,
            "listing_order": "last_activity_at desc",
            "organisations_in_pool": len(orgs),
            "candidates_considered": len(pool) + len(skipped),
            "projects": [
                {"project": p["path_with_namespace"], "organisation": org,
                 "id": p["id"], "default_branch": p.get("default_branch"),
                 "last_activity_at": p.get("last_activity_at"),
                 "picked_in_round": rnd}
                for org, p, rnd in picked],
            "skipped_no_default_branch": [
                {"project": p["path_with_namespace"],
                 "last_activity_at": p.get("last_activity_at")}
                for p in skipped],
        }
        return [make_repo(p["path_with_namespace"],
                          ref=p.get("default_branch"),
                          meta={"id": p["id"],
                                "default_branch": p.get("default_branch")})
                for _org, p, _rnd in picked]

    # ---- reading

    def tree(self, repo, path=""):
        """Paginated through to the end, bounded by TREE_PAGE_CAP.

        A project whose repository is not readable answers 403 here, not 404.
        That is what the ones listed without a `default_branch` answer, so they
        are skipped at selection and never reach this.
        """
        pid = urllib.parse.quote(str(repo.meta.get("id") or repo.key),
                                 safe="")
        entries, page = [], 1
        while page <= TREE_PAGE_CAP:
            params = {"per_page": 100, "page": page}
            if path:
                params["path"] = path
            if repo.ref:
                params["ref"] = repo.ref
            status, body, headers = self.http.get(
                "/projects/{}/repository/tree".format(pid), params)
            if status != 200 or not isinstance(body, list):
                return status, None, False
            entries += body
            nxt = (headers or {}).get("X-Next-Page")
            try:
                nxt = int(nxt)
            except (TypeError, ValueError):
                nxt = None
            if not nxt:
                return 200, [Entry(e.get("name", ""),
                                   "dir" if e.get("type") == "tree"
                                   else "file")
                             for e in entries], False
            page = nxt if nxt > page else page + 1
        return 200, None, True

    def file_text(self, repo, path):
        """The raw endpoint, whose path segment is encoded WHOLE.

        `safe=""`, so a slash becomes `%2F`. The unencoded form is a different
        route on this API and answers 404, which would read as "there is no
        such file" for a file plainly there: the under-claim that silently
        empties a sample.
        """
        pid = urllib.parse.quote(str(repo.meta.get("id") or repo.key),
                                 safe="")
        enc = urllib.parse.quote(path, safe="")
        status, body, _ = self.http.get(
            "/projects/{}/repository/files/{}/raw".format(pid, enc),
            {"ref": repo.ref} if repo.ref else None, text=True,
            headers={"Accept": "text/plain"})
        # text/plain, not base64-in-JSON: the shape differs from Forgejo's
        # contents API and reading it as JSON would make every file unreadable.
        return (status, body) if status == 200 else (status, None)

    def is_empty(self, repo):
        """False where a default branch exists, None otherwise. Never True.

        The documented proxy, and what it refuses to decide. See the module
        docstring.
        """
        return False if repo.meta.get("default_branch") else None
