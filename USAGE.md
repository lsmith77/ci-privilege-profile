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

## Running it instead of reading it

```sh
python3 -m ciprofile.differential \
    --profile data/ci_profile.json --cache data/ci_cache.json \
    --sample 8 --dry-run
```

Every other mode reads pipeline text. This one runs it: each selected
repository's pull-request workflows execute locally, in a container, with **no
secret of any kind supplied**, and the outcome is observed. It is the only
figure here that is not signal detection, and it reaches the cases static
reading cannot, because it does not have to *find* the test command.

**It executes untrusted third-party code on the machine you run it from.** A
pipeline is a script somebody else wrote for infrastructure they chose. It is
confined to a container, given no secret and no access to the host's container
daemon, and the clone is deleted afterwards; none of that makes it safe to
point at an arbitrary corpus, and `--dry-run` prints the selection and the
exact command without running anything. Start there.

**The measured outcome is not a green workflow.** Most pipelines fail under a
local runner for reasons that have nothing to do with privilege, so "green"
would measure the runner. The question is whether the check *executed*, with
nothing granted, without failing for a secret-related reason. Six outcomes,
three of which answer it:

| outcome | what it is evidence of |
| --- | --- |
| `ran-unprivileged` | every step ran and the job exited zero. Nothing granted was needed, and this is the one class that rests on an absence rather than on reading a log |
| `ran-with-failures` | a project command executed and failed on its own merits. Still an answer: the pipeline reached the project's own code with nothing granted |
| `secret-required` | the failing step's own output names a missing, empty or rejected credential |
| `environment-failure` | it failed for a reason belonging to the runner. **Proves nothing** |
| `timed-out` | that workflow file's own budget ran out. **Proves nothing** |
| `not-attempted` | the clone failed, no job was found, or the repository's ceiling was already spent when the file came up, so nothing was run for it. **Proves nothing** |

The classification of *failures* is heuristic and the positive case is not.
`ran-unprivileged` holds because no secret file is read, no secret is passed,
and credential-shaped variables are taken out of the runner's environment, so
nothing could have consumed one. Every other class is a reading of log text,
and **an unrecognised failure falls to `environment-failure`**, which supports
no claim in either direction. The asymmetry is deliberate and is the same one
the credentials axis holds to.

### The guards, and why each is there

| | |
| --- | --- |
| `--sample` is required, with no default, and refuses above a low ceiling unless `ALLOW_LARGE_SAMPLE=1` | the thing being multiplied is a container running somebody else's build, so a typo costs hours, and the consent question scales with it |
| no secrets file, in any spelling | the runner's *default* is to read `.secrets` from its working directory, which here is a clone of somebody else's repository. It is pointed at the null device, and the command line has no flag that could supply one |
| the runner's working directory is never the clone | it reads an `.actrc` out of its working directory, so a file in the corpus could otherwise add flags to the command measuring it |
| the host's container daemon is withheld from the workflow container | the runner mounts it by default, which would hand a third-party pipeline control of the daemon running it |
| `--timeout`, charged **per workflow file**, defaulted and overridable | 15 minutes by default, which is generous on purpose: a budget tight enough to cut a real run turns the measurement into a measurement of the host. Per file rather than per repository because the question is asked of a file, and a shared budget lets one slow workflow decide its siblings' answers |
| `--repo-ceiling`, on one repository's files together | an hour by default, so a repository with many slow workflows cannot hold the whole run. It is a ceiling and not a budget: nothing is cut short by it, and a file it leaves no room for is recorded as `not-attempted` rather than as `timed-out`, because nothing was run for that file and a timeout it did not have is a record of a run that never happened |
| the clone is temporary and removed in a `finally` | including when the runner raised, so a failed run leaves nothing of somebody else's repository behind |
| the daemon's growth headroom is checked before the first repository and again between each of them, and refuses below a 10 GB floor unless `ALLOW_LOW_DISK=1` | the risk is the machine rather than this tool's own appetite. Below the floor mid-run it stops with the results it already has, because a short run whose results survive is worth more than a long one that dies on a full disk. What it cannot see is a daemon that is internally full, which the Disk notes below set out |
| one at a time, with pacing between clones | the clones come from a mirror rather than from the upstream host, and a mirror on a constrained allocation finds a clone far more expensive than an API read |

### What you need installed, and what it costs

A container daemon, and `act` (a local GitHub Actions runner) **at 0.2.50 or
newer**. The floor is enforced rather than suggested: an older runner refuses
every action built on a Node runtime newer than node16, which is nearly every
action in current use, so a corpus measured with one would report an
environment failure almost everywhere and the distribution would read as a
finding. If the host carries two installs, put both directories on PATH; the
newest is the one used, so that PATH order does not decide what the
measurement says.

The runner reads GitHub Actions and no other grammar, so a GitLab, Woodpecker
or Jenkins pipeline cannot be sampled at all. **On an ARM host the runner
images are amd64 and run under emulation**, which dominates the cost: a small
dependency install and build takes minutes rather than seconds, and the first
repository also pays for the image pull. Budget accordingly.

### Disk

The tooling is **roughly 3.2 GB and is paid once**: the runner image measures
1.63 GB and the `act-toolcache` volume it fills measures 1.57 GB. **Each
additional repository wants about 2 GB** of transient container layers, and
those do not accumulate, because the container is removed per workflow file.
What does grow across a run is the toolcache, by whatever a workflow asks for
that it has not seen before, so a sample whose repositories want different
toolchain versions costs more than one that shares them. A first run of eight
repositories therefore wants single-digit gigabytes, not tens.

**Measured, on a run of 19 repositories: about 11 GB.** The daemon's growth
headroom went from 58.2 GB to 47.1 GB over that run. Plan with that for a
sample of this size rather than dividing it by the repository count: what grows
across a run is the toolcache, by whatever the sample's repositories do not
already share, so the cost does not scale with how many of them there are. Nine
of that run's records were failures that took a tenth of a second each, so for
a sample that actually runs the figure is if anything light. It is also why the
10 GB below is a floor and not a budget: one run of this size consumed more
than the whole of it.

**That is not the figure to plan around.** The run refuses to start below **10
GB of growth headroom for the container daemon**, and re-reads the figure
between repositories, because the machine is the risk and not this tool's
appetite: the host this was developed against carried 60 GB of images, 58 GB of
volumes and 47 GB of build cache from unrelated work against 54 GB of free
space, and a multi-hour run that dies at repository six has cost hours and
produced nothing. The refusal names the floor, what it found and how much to
free. Dropping below the floor part way through stops the run with the results
it already has and records the stop in the output. `ALLOW_LOW_DISK=1` proceeds
anyway, in the same shape as `ALLOW_LARGE_SAMPLE`.

The figure is the **daemon's** wherever it can be read, not the host's: on
macOS the daemon runs in a VM with a disk of its own, so a host with room to
spare says nothing about whether the next image pull fits. Where only the host
figure can be read, the output records that substitution rather than passing it
off as the daemon's. The headroom at the start and at the end of the run is
recorded either way, so a reader can see what the run cost.

**What the guard measures is growth headroom, and it is not the daemon's own
free space.** Where the daemon runs in a VM, the reading is how much further
that VM's disk image could grow into the host disk. So the guard protects
against filling the **host**; it does not detect a daemon that is internally
full. Those two differ, and in the direction that matters: a daemon whose own
filesystem is full while the host still has room passes the preflight, and the
symptom is a run that fails on a write although the preflight said yes. If that
is what you are looking at, the disk to free is the daemon's, not the host's.
The limitation travels with the figure, in the printed preflight and in
`differential_execution.json`.

The better figure is one container launch away and this tool does not take it.
`DOCKER_READ_ONLY` is every Docker command the module issues, each of them a
read, and nothing here creates a Docker object of any kind. That property is
worth more than a better number on a machine the tool was pointed at rather
than given, so the limitation is published instead of being measured away.

**Nothing is ever reclaimed for you.** The images, volumes and build cache on
the machine belong to whoever owns it, and a measurement instrument that
deleted them would be a worse failure than a run that declined to start. On a
refusal the harness prints what Docker reports as reclaimable and the commands
that would reclaim it, and stops there.

## Outputs

| File | What it is |
| --- | --- |
| `ci_profile.json` | A sweep's own profile: two scopes per repository, with signals and files |
| `ci_cache.json` | **Evidence, not conclusions.** Everything the sweep fetched, so a rule change costs no requests |
| `ci_profile_from_cache.json` | A cached re-analysis, which never overwrites the sweep's own profile |
| `fork_pr_profile.json` | The fork observation |
| `differential_execution.json` | A differential-execution run: the outcome per repository, the selection rule, and the runner it used |

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
| A differential-execution `ran-unprivileged` or `ran-with-failures` | **Yes, per repository**, which nothing else here is: the pipeline ran with nothing granted. Where the workflow holds no recognised test invocation it is a claim about the pull-request check and not about a test suite, and the output says which |
| A differential-execution `secret-required` | **Only with the log line beside it.** It is a reading of the failing step's output, and the reading is heuristic where the positive case is not |
| A differential-execution distribution | **No.** The sample is selected for what a local runner can execute, which is a selection on the properties under measurement. Report the per-repository outcomes, not a share |
| Any single repository's label | **No.** It is a hint. Read its `signals`. |
| Anything from `--limit`, a GitLab sample, or a partial cache | **No.** Every such output marks itself partial, loudly |

The **repository scope** describes what a project needs overall: a maintainer's
release workflow is a real requirement, just not one a contributor meets. It is
reported beside the pull-request scope and is not the figure to quote for the
contributor question.
