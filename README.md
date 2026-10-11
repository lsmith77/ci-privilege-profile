# ci-privilege-profile

For a corpus of repositories, this answers one question:

> **What privilege would each project's CI pipeline need in order to run, and
> could a contributor run the same checks on their own infrastructure?**

"Privilege" means the things a host has to *grant*: secrets, writes to anywhere
outside the run, access to the forge's own API, and runners the default one
cannot provide. Every repository is classified on one ladder, twice (once over
the workflows a contributor's own pull request triggers, and once over every
pipeline file), and the evidence behind each label is recorded alongside it so
a reader can re-slice it instead of trusting the label.

It reads Forgejo, GitLab, GitHub, and a local directory. It is read-only,
paced, and it under-claims whenever it cannot read something.

## What it cannot answer

First, because it is where this tool differs from what you would assume it
does.

**It does not run anything.** Every figure is signal detection over pipeline
text plus a structural reading of it. A rule can miss a signal (an action no
table has heard of, a deploy behind a `make release` target, a command
assembled from variables), and every miss pushes a repository *toward*
"self-contained", the flattering direction. A rule can also over-claim: the
string `docker push` in a disabled job reads the same as a live one. The
per-repository answer is a hint; a distribution over a corpus is a shape.
Neither is a measurement.

**It cannot tell you what a privilege is FOR, most of the time.** The tool
tries: a secret that only uploads coverage can be skipped, while a secret that
resolves private dependencies cannot. Of 361 repositories with a
pull-request-triggered pipeline in the corpus it was developed against, it
could read 158 as needing nothing granted and 24 as needing only a credential
that records results; **155 it could not read either way**. The derived figure
is "between 50% and 93%", which is too wide to use. The reason is not a missing
rule: in those cases the purpose of the privilege is simply not written down
anywhere in the configuration. [EXPERIMENTS.md](EXPERIMENTS.md#separating-a-secret-for-the-tests-from-a-secret-to-record-the-results)
records that in full, including three attempts to narrow the band that moved it
by about a point each.

**"Self-contained" does not mean "runs on a bare runner."** It means no secret,
no outward write, no special runner label. A hosted runner image ships with
node, python, java, go and docker already installed, so `npm test` on
`ubuntu-latest` is self-contained *and* assumes a toolchain somebody put there.
What a shared runner image would have to carry is reported separately, as
`assumes-toolchain` and the `toolchain-*` signals.

**It reads four locations and nothing else:** `.forgejo/workflows/`,
`.gitea/workflows/`, `.github/workflows/` and `.gitlab-ci.yml`. A project
driven by Travis, Jenkins, Drone, CircleCI, Woodpecker or Azure Pipelines has
a pipeline none of those holds. Root-level markers for those are recorded as
`other_ci` and counted separately, so `no-pipeline` is never to be read as
"this project does not do CI".

**It is not a sample of anything.** What you get out describes the corpus you
put in. A `--limit` produces a prefix of a listing, which is not a sample:
when that was first tried on a name-ordered listing, 17 of the first 25
repositories were organisation metadata repositories holding no software.

**Most of the uncertainty above is the corpus, not the tool.** In the corpus
this was developed against, only 361 of 1428 repositories have a pipeline a
pull request triggers; 220 of those 361 yield no identifiable test invocation;
and of the 326 fork pull requests landing on a repository that does check pull
requests, 264 carried no check at all, which is what starves the one instrument
that produces ground truth. [Why this class of corpus is hard to
measure](EXPERIMENTS.md#why-this-class-of-corpus-is-hard-to-measure) sets out
each property, the instrument it defeats, and the measured consequence.

**Start with [EXPERIMENTS.md](EXPERIMENTS.md).** If you have a corpus of your
own, that file says which parts of this design to keep and which to try
differently.

## The ladder

    acts-on-forge > writes-outward > read-credential > special-env
                  > self-contained > no-pull-request-trigger > no-pipeline

The first three rank by the **blast radius of the credential a host has to
grant**. `special-env` sits below them because a Windows, macOS, GPU or
self-hosted runner is a bill rather than a permission, and a bill is a smaller
decision than a trust decision. Below `self-contained` sit the two absences,
which only the pull-request scope can tell apart: a repository with pipelines
that no pull request triggers is not a repository with no CI.

Reported beside the class, never as one: `thin-wrapper` (every run step is a
single invocation, so a contributor can reproduce the pipeline by hand),
`uses-pull-request-target`, `uses-forge-token`, `assumes-toolchain`, the
`credentials-reporting-only` / `credentials-test-time` / `credentials-unclear`
axis, and the `test-step-unprivileged` / `test-step-privileged` /
`test-step-unidentified` determination.

That last one asks a narrower question than the credentials axis and is
answerable more often: not whether every privileged step in the scope is
droppable, but whether the step that **invokes the test suite** consumes a
credential. A credential reachable by inheritance from a workflow-level or
job-level `env:` counts as available to it, an unrecognised command form
answers "not identifiable" rather than "unprivileged", and where reachability
cannot be determined the step counts as privileged. Of the 361 repositories
above it reads 109 as having a test suite that runs unprivileged, and 220 as
not saying enough to tell.

Every repository gets both scopes. The **pull-request scope** is the one to
quote, because it answers what a contributor must be able to run. The
**repository scope** describes what a project needs overall, a maintainer's
release workflow included, and is reported beside it.
[USAGE.md](USAGE.md#which-figures-are-quotable) tabulates which individual
figures will bear weight and which will not.

## Scrutiny wanted

Each of these needs somebody outside this repository.

**Scrutiny of the rules and of the figures**, including re-derivation from a
corpus you control rather than this one. Every figure quoted here is recomputed
from an output file rather than carried in prose, so each is checkable against
the inputs, and the inputs are described well enough to rerun.

**Additional checks**, especially any that would catch a heuristic failing in
the flattering direction. Most of the known error modes push a repository
toward "self-contained". A missed signal leaves nothing in the output to
notice, so a fixture is the only place it can be caught, and a case with no
fixture is a case nothing tests.

**Other approaches.** The [approaches not
tried](EXPERIMENTS.md#approaches-not-tried) in EXPERIMENTS.md each carry an
assessment and the reasoning behind it, so you can disagree with an assessment
instead of repeating one. Entries elsewhere in that file record the approaches
that were tried and failed.

**Results from runs on other corpora.** [results/](results/README.md) holds the
write-ups, the fixed-field descriptor each one carries, and how to submit. A
run on a corpus that turns out to be unmeasurable is still a useful result:
saying which question a corpus cannot answer is worth recording, and the
seeded run is mostly that.

## Where to look

| | |
| --- | --- |
| [USAGE.md](USAGE.md) | How to run it against each forge, what it writes, which figures are quotable |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Every approach tried: what it cost, what it measured, what its limitation was. The failures included, and the one whose measured effect was zero |
| [results/](results/README.md) | Runs against real corpora, and the descriptor a result has to carry to be judged |
| [CONTRIBUTING.md](CONTRIBUTING.md) | The rules the code holds to, and where each module's argument lives |

## Where the question came from

The measurement was prompted by work on federation between public-sector
code-hosting platforms: when a contribution crosses an instance boundary the
pipeline runs on the contributor's side, so the receiving platform has to know
what privilege it is asking somebody else's instance to grant. A toolchain and
public registries is one proposition; a deploy key or a Windows runner is quite
another. That is what made "what privilege does this pipeline actually need" a
question worth measuring rather than assuming, and the design context is
[written up separately](https://codeberg.org/open-source-ecosystem/opencode-forges/src/branch/main/RUNNERS.md#user-content-federated-ci-two-trust-decisions-in-opposite-directions).

## How this was written

The code and the documentation were written by an AI assistant working in a
tight loop with a human reviewer who set the questions, supplied the corpus,
and decided what counted as evidence. That is worth stating plainly rather than
leaving a reader to infer it, because it shaped the result.

Several entries in [EXPERIMENTS.md](EXPERIMENTS.md) record approaches that were
proposed confidently and turned out to be wrong, and in more than one case the
diagnosis that failed was the assistant's and the correction came from checking
it against the data. The habit the log reflects, of recomputing every figure
from the source rather than carrying it in prose, exists because figures were
transcribed wrongly more than once and agreement between two accounts was
mistaken for confirmation. Treat the numbers here as checkable rather than as
authoritative: the inputs are described so that anyone can rerun them, and the
dead ends are recorded so nobody has to rediscover them.

## Licence

MIT. See [LICENSE](LICENSE). MIT because it is what CHAOSS itself uses for the
work it authors (the GPL-3.0 repositories in that organisation are the
GrimoireLab lineage it adopted, not its house style), so a tool written to be
donated there should arrive under the licence it would be maintained under.
