# Usage

How to run the tool against each forge, what it writes, and which of the
figures it prints will bear weight. [README.md](README.md) states what the tool
measures and what it cannot measure; read that first.

Python 3.7 or later. **Nothing is required to fetch**: the adapters are
stdlib-only, so this runs in an empty container. For *analysis*, PyYAML is used
if it is installed, which gives a real structural reading of each file instead
of an indentation-based one
([why](EXPERIMENTS.md#a-hand-rolled-block-parser-and-what-it-cost)). Without it
the tool degrades to the line reader, says so in every output, and still passes
its whole test suite: the two readings are asserted to agree on every fixture.

```sh
./test.sh                        # the whole suite: no network, no credential
python3 -m ciprofile --fixtures  # just the fixture corpus
```

## A local directory, with no network at all

```sh
python3 -m ciprofile --source local --root ./corpus
```

`./corpus` is either `<root>/<name>/…` or `<root>/<owner>/<name>/…`; each
top-level directory is judged on its own, so both layouts work without a flag.
This is how the fixtures run and how anybody can reproduce the tool's behaviour
without touching a forge.

Point `--root` at a `ci_cache.json` instead and it re-analyses that cache,
offline, with the socket layer taken away so a network call is impossible
rather than merely unintended.

## Forgejo or Gitea

```sh
FORGE_URL=https://forge.example.org FORGE_TOKEN=... \
    python3 -m ciprofile --source forgejo --out data
```

A token with repository **read** scope is enough (deliberately not an
administrative one), and a wholly public instance needs none. Emptiness comes
off the forge's own `empty` flag, which rides on the listing the candidates
came from, so it costs no extra request.

## GitLab

```sh
GITLAB_URL=https://gitlab.example.org \
    python3 -m ciprofile --source gitlab --sample 20
```

Unauthenticated and read-only by construction: there is no credential header in
that adapter at all, partly because one would change *what is visible* and make
a published sample unreproducible by anyone who does not hold the token.
`--sample` is **required with no default**, because no spelling of this mode
should start reading a platform somebody else operates without a person having
said how much of it to read; above 25 it refuses unless `ALLOW_LARGE_SAMPLE=1`.
The sample is stratified across publishing organisations rather than taken off
the head of the listing.

`empty_repo` is not exposed unauthenticated, so emptiness is read off a
documented proxy: a default branch means "not empty", its absence means
"unknown", never "empty".

## GitHub

```sh
GITHUB_TOKEN=... python3 -m ciprofile --source github --owner some-org
GITHUB_TOKEN=... python3 -m ciprofile --source github --repos list.txt
```

GitHub cannot be enumerated, so the corpus has to be named: an organisation or
user to walk, or a file of `owner/name` lines, which is how a corpus defined
elsewhere is fed in. Organisation profile repositories (`.github` and friends)
leave the denominator and are named in the output. Emptiness is read off the
message in GitHub's own 404 on the contents endpoint; the `size` field is
deliberately not consulted, because it is rounded to kilobytes and a repository
holding one small file can report zero.

The token needs no scopes. The remaining hourly budget is read from the
response headers and the run stops above a floor rather than spending the last
of it.

## Observing instead of inferring, on GitHub

```sh
GITHUB_TOKEN=... python3 -m ciprofile.fork_observation \
    --profile data/ci_profile.json
```

GitHub withholds repository secrets from fork pull requests and gives such runs
a read-only token, so **a workflow that has ever passed on a fork pull request
is proof that it runs without the repository's secrets**. That turns the
inference into an observation, and this joins it against a named profile to
show where the two disagree. A pass proves something; a failure proves nothing.

Its limitation is structural: it needs fork pull requests that were actually
checked. Over 1340 repositories of the corpus it was built against it found
1919 fork pull requests; 1853 of them had no checks attached at all, so it
could prove something about 17 repositories. [That is itself a
finding](EXPERIMENTS.md#observation-instead-of-inference-fork-pull-request-outcomes),
and not the one that was expected.

## Outputs

| File | What it is |
| --- | --- |
| `ci_profile.json` | A sweep's own profile: two scopes per repository, with signals and files |
| `ci_cache.json` | **Evidence, not conclusions.** Everything the sweep fetched, so a rule change costs no requests |
| `ci_profile_from_cache.json` | A cached re-analysis, which never overwrites the sweep's own profile |
| `fork_pr_profile.json` | The fork observation |

Each writer refuses the other files' names, by basename. A sweep of a sizeable
corpus costs hours, and a mode that overwrote another mode's output would
destroy a run in progress with no error anywhere.

The printed summary is the review gate: it prints both distributions, the
figures derived from them, the uncertainty band, and what moved since the
previous profile. For a corpus whose outputs are not in version control, that
diff is the only review a rule change gets.

None of those files is committed. What can be is a write-up of a run:
[results/](results/README.md) holds the runs against real corpora and the
descriptor each one carries.

## Which figures are quotable

The **pull-request scope** figures are the ones to quote. They answer what a
contributor must be able to run, which is the question the tool exists for.
Within those, in descending order of how much weight they will bear:

| Figure | Quotable? |
| --- | --- |
| The class distribution (how many repositories fall in each rung of the ladder) | **Yes**, as a shape, with the unknown count beside it |
| `no-pipeline`, with the `other_ci` count beside it | **Yes**, never on its own |
| `uses-pull-request-target` (the privileged-trigger count) | **Yes**; it is held strictly to the `on:` declaration |
| The forge-token split (how many repositories' class rests on that one judgement) | **Yes**; it exists to let a sceptic restate your headline |
| `assumes-toolchain` and the `toolchain-*` signals | **Yes**, as a statement about capacity, never about privilege |
| The `test-step-*` tally (what the step invoking the tests consumes) | **Yes** as three numbers together; the not-identifiable count is part of the answer |
| "Contributor-runnable if reporting steps are dropped" | **Only with its uncertainty band**, which is usually larger than the figure |
| "With a test suite that runs unprivileged" | **Only with the not-identifiable count beside it**, which is the larger number; it is a positive claim about the test steps the tool could find, never about the ones it could not |
| Any single repository's label | **No.** It is a hint. Read its `signals`. |
| Anything from `--limit`, a GitLab sample, or a partial cache | **No.** Every such output marks itself partial, loudly |

The **repository scope** describes what a project needs overall: a maintainer's
release workflow is a real requirement, just not one a contributor meets. It is
reported beside the pull-request scope and is not the figure to quote for the
contributor question.
