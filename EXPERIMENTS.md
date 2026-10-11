# Experiments

Everything tried on the way to the current design, in the order it happened:
what each approach was for, what it cost, what its limitation was, and what it
led to. Negative results are in here on equal terms: several of them are the
most useful entries, and the longest one ends in a figure too wide to quote.

The point of this file is that somebody can **retrace the reasoning** rather
than inherit the conclusion, and so judge which *other* approaches are worth
trying. If you are building something of this shape, the entries worth reading
first are [Caching the fetched text, and doing it too
late](#caching-the-fetched-text-and-doing-it-too-late), [A failed hypothesis,
with a measured effect of zero](#a-failed-hypothesis-with-a-measured-effect-of-zero),
and [Separating a secret for the tests from a secret to record the
results](#separating-a-secret-for-the-tests-from-a-secret-to-record-the-results).

## The corpus the measurements come from

Unless an entry says otherwise, the figures below were measured over one
corpus: about 1400 repositories published by organisations that release
software without being software vendors, mirrored onto a single self-hosted
forge, overwhelmingly GitHub Actions upstream. It is not a sample of anything
and no share quoted here describes "open source" or any other population. What
the numbers are good for is the *size of an effect* (whether a rule change
moves a figure by a rounding error or by a third of the corpus), and that is
how they are used.

Two scopes appear throughout. The **pull-request scope** is the workflows a
contributor's own pull request triggers; the **repository scope** is every
pipeline file. The first is the figure the tool exists to produce.

---

## Why this class of corpus is hard to measure

The bands in the entries below are wide, and most of the width is the corpus
rather than the instruments. Signal detection over pipeline text, the
credentials axis, the narrower test-step determination and the fork
pull-request observation are independent of each other, and each one hit a
different wall. The walls are not defects in the instruments: each is a
property that a corpus of organisations releasing software without being
software vendors tends to have, which is why they are set out here rather than
inside any one entry.

The figures are one corpus's, recomputed from its profile and its fork
observation. The denominator is all 1428 classified repositories, organisation
profile repositories included, which is the basis the entries below and
`README.md` use; the run write-up in [results/](results/README.md) excludes
those repositories and states the same quantities over 1409.

**Most projects do not check pull requests.** 361 of 1428 classified
repositories have a pipeline that a pull request triggers, a little over a
quarter. 880 hold no pipeline this tool reads at all and 187 hold pipelines
that no pull request sets off. Everything measured about contributor-side CI
applies to that quarter; the rest of the corpus is outside the question rather
than answered by it, and a share quoted without that denominator will be read
as a share of the corpus.

**Contribution from outside exists but is thin, and CI almost never runs on
it.** 253 of the 1340 repositories the fork observation reached carry any fork
pull request at all. Of the 326 fork pull requests landing on a repository that
does check pull requests, 264 carried no check of any kind, four in five. That
starves the one instrument that produces ground truth: a workflow that passes
on a fork pull request proves it needs no repository secret, because the host
withholds secrets from such runs, and that evidence is generated only where
somebody let the check run. Across the 1340, the observation proved something
about 17. [Observation instead of inference](#observation-instead-of-inference-fork-pull-request-outcomes)
records the method and the join the unchecked figure cannot be quoted without.

**The test command is usually not in the pipeline file.** Of the 361
repositories with a pull-request-triggered pipeline, 220 yield no identifiable
test invocation, roughly three fifths. The tests sit behind a project shell
script, a make or task target, a reusable workflow in another repository, or a
composite action, and static reading cannot follow any of those. [Narrowing the
band by asking only about the test
step](#narrowing-the-band-by-asking-only-about-the-test-step) groups that
residual by cause, and reading a sample of the largest group out of the
evidence cache found no missing cluster worth a rule.

**The purpose of a credential is not written down.** Configuration records that
a secret is used, never what it is for. Of the 185 repositories whose
pull-request scope holds a credential for the axis to classify, 24 read as
recording a result and 6 as needed by the tests, while 155 read as neither:
separating a credential the tests need from one that only uploads a result is
undecidable from the file in most cases. [Separating a secret for the tests
from a secret to record the
results](#separating-a-secret-for-the-tests-from-a-secret-to-record-the-results)
is that finding in full, including the attempts to narrow it.

**A corpus of mirrors measures somebody else's runners.** Where the
repositories are mirrors of upstreams hosted elsewhere, the pipelines were
written for the upstream platform's hosted runners and have never run on the
platform holding the mirror. Every repository in this corpus is such a mirror.
The distribution therefore says what privilege those pipelines need and nothing
about what they would cost the platform that holds them, which is the reading
such a corpus most invites.

**The instruments are not independent of the thing being measured.** Low
contribution and unoperated checks are both what the measurement is trying to
characterise and what prevents it from being characterised. The observation
needs checked fork pull requests before it can produce evidence, and a corpus
with little contribution and few operated checks supplies neither. No addition
to the rule tables reaches that.

What improves the figures is more evidence, not a closer reading of the same
files. They improve as contribution accumulates, so re-running the observation
over the same corpus later is the cheapest improvement available, and the
baseline has to be taken before anything moves because no later sweep can
reconstruct it. Generating the evidence directly, by executing a pipeline with
its secrets stripped, is the only instrument that works on a repository nobody
has contributed to; what it decided on a first sample, and what it cost, are in
[differential execution](#differential-execution-running-the-pipeline-with-nothing-granted).

---

## Privilege-class ladder

**The question.** For a repository, what single thing best describes what its
CI would need from whoever runs it?

**What was done.** Each repository is classified by the most privileged thing
its pipeline needs, on one ordered ladder:

    forge-API write > outward write > read-only credential > special runner
                    > self-contained > no pull-request trigger > no pipeline

The order is not arbitrary and is the part worth arguing with. The first three
rank by the **blast radius of the credential a host has to grant**: a token
against the forge API can rewrite the project's own issues, labels and
releases, and on a shared instance that is the trust decision; an outward write
can reach a registry, a server or a cloud account, which is somebody else's
blast radius but not the host's; a read-only credential is a secret that still
has to be held and can still leak, but grants no write anywhere. A special
runner (Windows, macOS, GPU, self-hosted) ranks **below all three** because
it is a bill rather than a permission, and a bill is a smaller decision than a
trust decision.

**Measured effect.** None to report: this is the frame the later measurements
are expressed in, not a change to one.

**Limitation that remains.** It is signal detection over pipeline text, not
parsing and certainly not execution. A rule can miss (pushing a repository
*down* the ladder, the flattering direction) and a rule can over-claim (pushing
it *up*). The per-repository answer is a hint; the distribution is a shape.

**What it led to.** Everything else here. The ladder is what made it possible
to notice that a figure had moved at all.

**If you are starting fresh.** Decide the order of your classes before you
write a single rule, and write down the argument for it. Every later dispute
(the forge-token carve-out, the permission grants, the reporting axis) turned
out to be a dispute about the order, and having the argument already written
down is what made those disputes short.

---

## Whole-repository versus trigger-scoped classification

**The question.** Does "what this project's CI needs" answer "what a
contributor would need"?

**What was done.** Initially the signals were unioned across every pipeline
file in a repository. The failure showed up by inspection first and then by
measurement: a repository whose pull-request check was a pure lint run
classified as `writes-outward`, because an unrelated release workflow ran `npm
publish`.

**Measured effect.** Since nearly every mature project carries a release or
deploy workflow, this understates the self-contained share **in bulk rather
than at the margin**. Over the corpus, reading every file as one set gives 91
self-contained repositories; scoping to what a pull request actually triggers
gives 158. `writes-outward` falls from 206 to 67 the same way. The fix changed
the headline by three-quarters of its own size.

**Limitation that remains.** A contributor pushing a branch to their own fork
also runs that fork's `push`-triggered workflows, and the pull-request scope
excludes those. A project whose checks hang off `push` therefore reads lighter
here than a contributor's infrastructure would actually need. `push` is not
folded in because a scope that admits it admits most release workflows with it,
which is exactly the reading the split exists to separate out, so the
repository scope is reported beside the pull-request one and is the nearer
answer for such a project.

**What it led to.** Two profiles per repository, everywhere, and the discipline
that every output says which of them is the figure to quote. It also led to
`no-pull-request-trigger` as a class of its own: a repository with pipelines
that no pull request sets off is not a repository with no CI, and merging them
inflates `no-pipeline`, which is among the figures most likely to be quoted.

**If you are starting fresh.** Work out whose question you are answering before
you aggregate anything. "Per repository" is almost never the right unit on its
own; the unit is usually "per repository, under the conditions the asker cares
about".

---

## Excluding organisation profile repositories

**The question.** Why did a first cheap sample look like nobody runs CI?

**What was done.** A first pass with a limit of 25 repositories returned 20
"no pipeline" results. Reading the 25 names explained it: 17 of them were
per-organisation `.github` metadata repositories, which hold issue templates
and funding files and no software at all, and which sort early in a
name-ordered listing because of the leading dot.

**Measured effect.** 17 of 25 in the sample; the correction removes them from
the denominator entirely rather than counting them as projects that do no CI.

**Limitation that remains.** The exclusion is by exact name
(`.github`, `.gitlab`, `.forgejo`, `.gitea`). Other non-software repositories,
among them documentation sites, issue trackers and asset dumps, are still in
the denominator, and there is no general test for "this repository is not
software".

**What it led to.** The exclusion list, which is *named in the output* rather
than applied silently, and a rule applied everywhere since: any limit is
recorded as making the profile partial.

**If you are starting fresh.** A prefix-ordered sample is not a sample. If a
cheap first pass gives a striking answer, read the names before believing it.

---

## Distinguishing "empty repository" from "could not read"

**The question.** A root listing answered 404. Does that mean there is no
pipeline?

**What was done.** It was being recorded as "no pipeline". But a repository
with nothing in it and a repository whose default branch is unborn or missing
answer the root listing identically, and for a mirrored or imported corpus the
second cause is live: a failed initial sync looks exactly like a project that
does no CI. The fix is to stop inferring from the status code and ask the forge
for its own emptiness answer, then record a contradiction as unknown.

**Measured effect.** Two repositories in the 1428-repository corpus were being
silently counted as doing no CI when their mirror had an unborn default branch.
Small in absolute terms, invisible in the output, and in the direction that
flatters the headline.

**Limitation that remains.** The three forges expose emptiness differently and
one of them cannot answer at all. Forgejo carries an `empty` flag on its
repository listing. GitHub says so in the message body of its own 404 on the
contents endpoint. GitLab's unauthenticated project listing exposes neither
`empty_repo` nor `repository_access_level`, so the adapter uses a documented
proxy: a default branch means "not empty", and its absence means "unknown"
rather than "empty", because a project with the repository feature disabled
answers 403 exactly like an empty one from outside. The consequence is that a
genuinely empty GitLab project leaves the distribution as unknown instead of
counting as `no-pipeline`. That is the under-claiming direction, deliberately.

**What it led to.** `is_empty()` being part of the source-adapter interface
rather than a detail inside one adapter, with three answers (`True`, `False`,
`None`), and `None` explicitly not meaning "not empty".

**If you are starting fresh.** Find every place where "absent" and "could not
read" produce the same bytes, and make the difference someone else's job to
answer rather than yours to infer. A silent under-count is worth more attention
than its size suggests, because it is in the direction you want to believe.

---

## The forge-minted token carve-out

**The question.** Is `secrets.GITHUB_TOKEN` a credential a contributor would
have to be given?

**What was done.** No. It is minted by whichever forge runs the job, so a
contributor supplies nothing for it, and the same goes for `GITEA_TOKEN`,
`FORGEJO_TOKEN` and GitLab's `CI_JOB_TOKEN`. But treating them as ordinary
credentials would have been the single judgement that most moved the headline,
and treating them as nothing would hide a real forge-write capability. The
resolution is to record them as their own signal, raise `acts-on-forge` only in
company with an actual forge-write signal, and **publish the split**.

**Measured effect.** In the pull-request scope, over all 1428 classified
repositories: 97 reference a forge-minted token. 33 of them also carry a
forge-write signal, so they are `acts-on-forge` on their own evidence and the
carve-out decides nothing for them. **64 carry no forge-write signal at all**:
their class rests entirely on this judgement. That second number is the size of
the disagreement, so anybody who thinks the carve-out is wrong can restate the
headline under the stricter reading without re-running anything.

**Limitation that remains.** The carve-out is right about who supplies the
token and says nothing about what the job does with it. A `permissions:` block
can widen the forge token's scope, and a workflow that uses it to push a commit
is caught only by the push signal, not by the token.

**What it led to.** A general habit: where a single judgement moves a headline,
publish the number that sizes the disagreement rather than the argument for the
judgement.

**If you are starting fresh.** For each contested rule, ask what number would
let a sceptic re-derive your headline under their reading. If there is one,
print it. It is cheaper than the argument and it ends the argument.

---

## A credential-name heuristic and its false positives

**The question.** How do you detect a credential in a grammar with no
`secrets.` namespace?

**What was done.** By name. GitLab has no `secrets.` reference, so a masked
variable can be recognised by nothing but its spelling, and variable names
ending in a credential-shaped suffix (`_TOKEN`, `_PASSWORD`, `_SECRET`,
`_KEY`, `_PAT`, `_AUTH`, …) are read as secrets. The scan runs over both
grammars, so an Actions workflow's `$API_KEY` raises it too.

**Measured effect.** `CACHE_KEY` matched. It is among the commonest variable
names in Actions, because a cache key is routinely computed into one, and
matching it moves repositories out of `self-contained` and into
`read-credential`, the exact figure the tool exists to produce. Sharpening the
pattern cannot fix it: `API_KEY` and `CACHE_KEY` are spelled the same way and
both populations are real.

**Limitation that remains.** The fix is an explicit exception list of names
that look like credentials and are not: cache keys, sort keys, idempotency
keys, translation keys. It matches **exact names only**, so a prefixed spelling
such as `NPM_CACHE_KEY` still misfires until somebody adds it, and an inline
test password still reads as a credential. The list is checked both ways by the
test suite: every entry must be a name the suffix rule would otherwise have
claimed, and a set of real credential names must stay out of it.

**What it led to.** The general preference for an exception list over a cleverer
regex. The list is readable, checkable and extensible by anybody; a regex whose
judgement is unreadable is not.

**If you are starting fresh.** Where a heuristic has to stay, make its failures
enumerable rather than implicit, and test the enumeration in both directions.

---

## Cross-corpus testing found bugs the home corpus did not

**The question.** Does the rule set work on a corpus it was not written
against?

**What was done.** The GitLab adapter was pointed at a stratified sample of
twenty projects on an unrelated platform. It was built to find GitLab idioms
the rules miss.

**Measured effect.** It found three defects, all of them in the **GitHub
Actions** rules, which is not what it was looking for:

- a conditional `push:` input on the standard build-and-push action was read as
  build-only, although the expression form is exactly what the vendor's own
  starter workflow emits;
- `actions/github-script` counted as a forge write even where the script body
  only calls `core.*` and never touches the authenticated client;
- `packages: write` and `id-token: write` were not signals at all, the second
  mattering disproportionately because a keyless publish carries no credential
  for any other rule to detect.

Fixing all three, measured on the pull-request scope of the 358 of 1409
repositories left once organisation profile repositories leave the denominator:
read-credential 60 → 47, outward writes 50 → 67, self-contained 161 → 158. Over
the 361 of 1428 the rest of this file is measured on, those three post-fix
figures are the same, because the only class the two bases disagree about is
`acts-on-forge`, 70 against 73, and it is not one of them. **The self-contained
figure barely moved.** The correction changed *which privileged class*
repositories fell into, not *how many* needed no privilege.

**Limitation that remains.** The sample was twenty projects; it cannot say what
share of anything is anything, and its own output says so in several places.
Cross-corpus testing finds defects it happens to walk into.

**What it led to.** The second source adapter being kept permanently, and then
a third, rather than being a one-off diagnostic. Also the habit of reporting
what a correction moved *and* what it did not: "the headline barely moved" is
a result worth printing, because it tells the reader which number is robust.

**If you are starting fresh.** Run your rules against a corpus you did not
write them for, as early as you can afford to. The defects it finds will mostly
not be in the part you were testing.

---

## A failed hypothesis, with a measured effect of zero

**This one failed.** The uncertainty band was large and the diagnosis offered
for it was wrong.

**The question.** Why are so many repositories `credentials-unclear`?

**What was done.** The diagnosis offered was that ordinary build plumbing
(checkout, toolchain setup, cache restore and save, artifact upload) was being
counted as unrecognised privilege, because a name-shaped credential guess would
land on such a step and then nothing would recognise what the credential was
for. So a list of "neutral" actions was built: steps that plainly consume no
privilege, with the rule that membership never overrides a credential handed
explicitly to the step.

**Measured effect.** **It changed no number at all.** Not the band, not the
distribution, not one repository's class.

The reason is worth more than the change would have been. The census behind the
diagnosis had counted every action appearing in the affected *files*, and
`actions/checkout` appears in nearly every file, so it topped the list. The
population that actually mattered was the steps **flagged as unrecognised
privilege**, which is a different and much smaller set. Re-censused correctly,
checkout appeared once, and only because it had been handed a token.

**Limitation that remains.** The list is kept, because the property it states is
still the right one and it protects the asymmetry from a future rule that does
land on build plumbing. What it is not is a fix for the band.

**What it led to.** One rule, applied since: **census the population you are
actually reasoning about.** Not the files it lives in, not a superset that is
easier to count: the exact set whose behaviour you are trying to explain.

**If you are starting fresh.** When you have a diagnosis for a large residual,
write down the population your evidence is drawn from and check it is the
residual's population. A plausible diagnosis drawn from the wrong census costs
real work and leaves the number where it was.

---

## A hand-rolled block parser, and what it cost

**This one failed, expensively, and was found by measurement rather than by
reading.**

**The question.** How do you cut a workflow file into steps without a YAML
parser?

**What was done.** By indentation. A `steps:` key bounds its own block, and
each list item inside it bounds a step. That reasoning is correct for the shape
everybody writes by hand and wrong for a shape that is equally legal: a
sequence whose items sit at the key's own column, not indented past it.

```yaml
jobs:
  build:
    steps:
    - uses: actions/checkout@v4
    - run: mvn -B verify
```

Read by the indentation rule, that `steps:` block is empty. Every privilege in
such a job then lands in "the frame" (the part of the file no step could be
held responsible for), so a workflow whose steps are merely unindented reports
an unattributable privilege, and nothing downstream can say what the credential
was for.

**Measured effect.** 81 of 505 pull-request-scope files in the corpus were
written that way: a sixth of the evidence, with its attribution destroyed. The
effect was invisible in the class distribution, because the class comes from
the file as a whole; it showed up only in the reporting-versus-test-time axis,
where "a privilege nobody could be attributed" is a distinct signal that was
being raised far too often.

**Limitation that remains.** The line reader was taught that one shape, and it
is still a line reader. A real parser is now used wherever one is installed, and
the two readings are asserted to agree on every fixture, but they can still
differ in the long tail. Measured over the same 1428-repository corpus, the two
readings disagree about **exactly one repository**, and in the harmless
direction: a flow sequence written on the line *after* `on:`

```yaml
on:
   [push]
```

is undeterminable to the line reader, which keeps the file in the pull-request
scope (over-claiming), and plain to the parser, which correctly takes it out.

**What it led to.** The split this repository now holds to: **the no-dependency
constraint belongs to the fetching side, which runs in a container, not to the
analysis side, which runs on a laptop.** Fetching is stdlib-only and always
will be. Analysis uses a real parser when one is available and degrades to the
line reader when it is not, and every output records which reading produced it.

**If you are starting fresh.** Do not hand-roll structure out of indentation if
you can avoid it. If you must, find the legal shapes you are not handling by
*counting them in your corpus*, not by reading your own code: the defect was
sitting in a sixth of the files and reading the code never found it.

---

## Separating "a secret for the tests" from "a secret to record the results"

**This is the central negative result, and the most useful entry here.**

**The question.** If a pipeline's privilege is only used to upload coverage or
comment on a pull request, a contributor can run the tests by skipping those
steps. So the contributor-runnable share should be much larger than the
self-contained share. How much larger?

**What was done.** An axis was built across every privileged class, asking of
each privileged *step* what the privilege is **for**:

- known reporting actions matched **by exact name**: coverage uploaders,
  test-result publishers, code-quality scanners, pull-request commenters, chat
  notifiers;
- how the step is written: `if: always()`, `if: failure()`,
  `continue-on-error: true`. A step the tests depend on is not written that way.
  Its one exception is a teardown, which is written exactly that way so the
  resources go away after a failure too;
- the **inverse** signal, and deliberately decisive: dependency-resolution
  credentials. A private npm, Maven, NuGet, Composer, Bundler or Cargo
  registry, a credentialed pip index, a `git config … insteadOf` rewrite, a
  `docker login` before a `docker build`. Without those there is nothing to
  compile, so the privilege is not droppable at any price.

The asymmetry was enforced deliberately: **a single unrecognised privileged
step forces "unclear"** and can never leave a scope "reporting-only", because
"reporting-only" is a positive claim about *every* privileged step in the
scope. Without that rule the flattering answer wins by default for every tool
the tables have never heard of, and the figure becomes a measure of the tables
rather than of the corpus.

**Measured effect: the band did not collapse.** Of the 361 of 1428 classified
repositories with a pull-request-triggered pipeline:

| reading | repositories |
| --- | ---: |
| self-contained: needs nothing granted as written | 158 |
| reporting-only: privilege is entirely a record of the run | 24 |
| test-time: the credential is what makes the tests possible | 6 |
| **unclear: one privileged step recognised as neither** | **155** |

The derived figure is therefore "**between 50% and 93%**" of repositories with
a pull-request pipeline could have their checks run by a contributor. That is
too wide to use for anything.

Three further attempts to narrow it moved the floor by about one point each.
Reading the remaining cases out of the evidence cache shows why, and the reason
is not a missing rule: **their privilege is real and its purpose is simply not
written down anywhere in the configuration.** A secret named for nothing in
particular, handed to a build that could be doing either thing, is not a
question static analysis can answer, because the answer was never recorded.

**Limitation that remains.** It is the finding. Static analysis of
configuration cannot answer a question the configuration does not state. The
axis is kept because it is honest about which cases it cannot read, and because
the 24 it does read are real; what it is not is a way to narrow the band.

**What it led to.** Two things. The uncertainty band is printed beside the
derived figure *every time*, never alone: a single number there would be read
as a measurement. And the search for a way to **observe** rather than infer,
which is the next entry but one.

**If you are starting fresh.** Before building a classifier for intent, ask
whether the intent is recorded anywhere in what you are reading. If it is not,
you are measuring your own table. Build the thing anyway if the asymmetry can
be made honest. But publish the band, and treat a band this wide as a result
rather than as a bug to be fixed.

---

## Narrowing the band by asking only about the test step

**The question.** The axis above asks whether *every* privileged step in a
scope is droppable, and one step nothing recognised holds the whole scope
unclear. That is the right rule for that question and it is what leaves 155 of
361 repositories unreadable. A narrower question should be answerable more
often: **does the step that actually invokes the test suite consume a
credential?** If it does not, the tests can run without the project's secrets
whatever the publish and reporting steps around them need, which is what a
contributor wanting a pre-flight signal is asking.

**What was done.** A per-scope determination with three values, off the
precedence ladder and changing no primary class, reported as its own tally
beside the credentials axis:

- `test-step-unprivileged`: an identified test invocation with no credential
  available to it;
- `test-step-privileged`: one with a credential available;
- `test-step-unidentified`: no test invocation could be identified.

Three things had to be got right, in descending order of how badly getting them
wrong would mislead.

**Inherited environment, which is the trap.** A credential mapped in at
workflow level or job level `env:`, or in GitLab's global or job `variables:`,
is in the environment of every step in that scope including the test step,
although the step names no secret. The existing unit segmentation could not
answer this: `privilege_units()` returns the steps plus **one frame for the
whole file**, which is exactly right for asking whether a privilege is
unattributable and useless for asking whether one is reachable from a given
step, because a credential in the publish job's `env:` sits in the same frame
as the test job's steps. So a second reading was added,
`structure.units_with_scope()`, which hands each step the workflow's own
top-level keys plus the keys of the one job it sits in, minus that job's
`steps:` block. In the corpus the difference is 6 of the 361 read as privileged
through inheritance alone that the step's own text would have called clean.

**The error direction.** Where whether a credential reaches the test step
cannot be settled, the step is privileged. That covers a step whose enclosing
scope could not be cut out of the file and a GitLab file whose variables come
from an `include:` or an `extends:`, and it is the same asymmetry the
credentials axis enforces.

**Recognition, not inference.** An explicit list of test-invoking command
forms, and an unrecognised form yields "not identifiable" rather than
"unprivileged". The direction matters both ways here, which is why the list is
kept to forms that mean a test run and nothing else: a missed form costs a
reading, while a spurious match on a clean step would hand out the flattering
answer for free.

**Measured effect: it resolves about a third of the unclear band, and the
useful answer in about a fifth.** Of the 361 of 1428 classified repositories
with a pull-request-triggered pipeline:

| determination | repositories | of the 155 unclear |
| --- | ---: | ---: |
| test-step-unprivileged | 109 | 35 |
| test-step-privileged | 32 | 18 |
| **test-step-unidentified** | **220** | **102** |

So the determination says something about 53 of the 155 repositories the
credentials axis could not read, and of those 35 say the tests run
unprivileged. **That is a real gain and it is not the gain that was hoped
for**: two thirds of the band is unresolved, and for the same reason the band
exists at all. The obstacle is no longer the purpose of a privilege being
unrecorded; it is that **the test invocation itself is not in the file**. The
residual, grouped by cause over the 252 of the 361 not read as unprivileged:

one bucket each, so the column sums:

| obstacle | repositories |
| --- | ---: |
| unidentified: run steps present, no recognised test form (project shell scripts, docker-compose harnesses, nix/devenv wrappers, `${{ inputs.test-command }}`) | 84 |
| unidentified: every step is a call out of the file, a reusable workflow or a composite action | 53 |
| unidentified: the tests are behind a script or a make/task target this cannot look into | 37 |
| unidentified: no run or script step at all, only actions | 26 |
| unidentified: GitLab script lines, none recognised | 20 |
| privileged: a credential named in the test step itself | 14 |
| privileged: a dependency-resolution or cloud credential the tests need | 6 |
| privileged: a credential inherited from a workflow-level or job-level `env:`/`variables:` | 6 |
| privileged: a privileged act in the same step as the test invocation | 4 |
| privileged: GitLab `include:`/`extends:`, so the variables are in text never fetched | 2 |

Reading a sample of the largest bucket out of the evidence cache showed **no
missing cluster worth a rule**: it is dominated by workflows that are not test
workflows (releases, labelling, image builds) and by test harnesses whose entry
point is a name only the project knows. One addition came out of the sample,
`ant … test`, and it moved exactly one repository.

**Limitation that remains.** The three obstacle groups at the top of that table
are the same obstacle in three spellings: the command that runs the tests is
somewhere this tool does not read. No extension of the command list reaches
them, and the five `unidentified` rows together are the sample a
[differential-execution](#differential-execution-running-the-pipeline-with-nothing-granted)
run would have to cover, which is the one approach that would. A first sample
of eight drawn from exactly those rows answered four of them, so the approach
does reach the band; what it does not reach is the scale.

**What it led to.** The determination is kept, because 109 repositories with a
test suite that demonstrably runs unprivileged is a stronger and narrower claim
than anything the credentials axis produces, and because its band is reported
beside it every time. The forge-token carve-out was measured here too and
**changed no repository's determination**: 14 of the 361 have a test step
reached by the forge's own auto-minted token, and all 14 also have a real
credential reaching one, so the judgement that moves the headline distribution
moves nothing at all in this figure.

**If you are starting fresh.** Narrowing the question is worth trying before
adding rules to a wide one; it moved more here than three attempts at narrowing
the band did. But check first where the thing you are narrowing *to* is
written. The purpose of a credential is not in the file, and neither, often, is
the name of the test command.

---

## Caching the fetched text, and doing it too late

**The question.** Why does every rule change take an afternoon?

**What was done.** Two full sweeps of about a hundred minutes each were spent
before the fetched pipeline text was cached. Every change to a rule required
another one, against a rate-limited, CPU-capped host. Caching everything the
sweep fetched (the file texts, the root listing's status, the forge's own
emptiness answer, the foreign-CI markers) made re-analysis free and entirely
offline.

**Measured effect.** A rule change went from ~100 minutes and a few thousand
requests to about 3 seconds and none.

**Limitation that remains.** A cached re-analysis describes the corpus **as of
the cache date**, and corpora move. So the cache stores *evidence and no
conclusions*: the rules are re-run over the stored inputs rather than replayed
out of stored verdicts, which is what lets the emptiness rule itself be changed
and re-derived. Every output from it carries a banner saying when it was
fetched, in the first key of the JSON and above *and* below the printed
figures, with `scanned` set to the fetch date rather than to today. It refuses
outright on a cache that is missing, unreadable, undated, of the wrong version,
or marked partial.

**What it led to.** The "no network" guarantee being *asserted* rather than
promised: the cached path takes the socket layer away before it opens the
cache, so a later edit that reached for one more field raises instead of
quietly spending a request.

**If you are starting fresh.** **Build the cache first.** Not in the fourth
version, but in the first one, before the first full sweep. And make a cached
re-analysis say loudly that it describes the corpus as of the cache date; it
must never be able to pass for a fresh measurement.

---

## Observation instead of inference: fork pull-request outcomes

**The question.** Can the inference be checked against something that is not
another inference?

**What was done.** Yes, on one forge. GitHub withholds repository secrets from
pull requests opened from a fork and gives such runs a read-only token, and the
organisation settings that lift either half are available to private
repositories only. For a public repository, therefore, **a workflow that has
ever passed on a fork pull request is proof that it runs without the
repository's secrets.** That converts the inference problem into an
observation, per repository, from published data.

**Measured effect.** Two traps were found while building it, and either would
have produced a flattering wrong answer:

- a `pull_request_target` run executes **in the base repository's context, with
  its secrets**. A green one proves nothing, so the workflow run's own `event`
  is checked for every passing pull request rather than the rollup state being
  taken at face value;
- the aggregate check rollup spans third-party commit statuses as well as
  Actions check runs, and a third-party provider's secret model is its own. A
  pass backed by nothing but foreign statuses is reported as unproven.

So a repository is called secret-free-proven only where some passing fork pull
request carries an Actions check run whose own workflow run was triggered by
`pull_request`. The asymmetry is total: a pass proves the pipeline needs no
repository secret; **a failure proves nothing**, because the change itself may
be what failed. It measures a floor, never a ceiling.

**Limitation that remains, and it is structural.** The method only works where
fork pull requests exist *and were checked*. Run over 1340 repositories of the
corpus, it found 1919 fork pull requests across 253 repositories; 1903 of them
came from a fork someone else owns, so external contribution is real and not
rare.
But:

| | |
| --- | ---: |
| fork pull requests found | 1919 |
| …with **no checks attached at all** | 1853 |
| …passed | 44 |
| …failed (which proves nothing) | 20 |
| repositories with a passing fork pull request | 21 |
| repositories where that pass is **proven** secret-free | 17 |

So the method yields evidence about **17 of 1340 repositories**, a little over
one percent.

**The raw "no checks" figure must be joined before it is quoted, and the join
changes what it means.** Of the 253 repositories with fork pull requests, only
80 have a pipeline a pull request triggers at all. Splitting the fork pull
requests on that:

| | repos | fork PRs | no checks |
| --- | ---: | ---: | ---: |
| repositories **with** a pull-request-triggered pipeline | 80 | 326 | 264 (81%) |
| repositories **without** one | 172 | 1498 | 1494 |
| absent from the profile | 1 | 95 | 95 |

So the quotable figure is **264**, not 1853. For the 1494 there was no pipeline
to attach, and calling those unchecked would be counting the absence of CI as a
gate that nobody opened. What survives the join is still a real finding (four
in five fork pull requests to a repository that *does* check pull requests
carried no check), but it is an order of magnitude smaller than the raw count,
and it is the only version of the claim that an outside reader cannot take
apart.

**A low figure is the expected reading for a corpus of this kind, and not a
negative result about the method.** The corpus is a set of mirrors of projects
whose development happens somewhere else, on a platform early in its own life
where contributing is not yet possible at all. Nothing in that setting could
produce high check coverage, so finding little coverage confirms the setting
rather than discrediting the observation. And what the observation found is a
gap in practice, not a shortage of capacity: the gate exists in those 80
repositories and was not operated on four contributions in five. The reasons
available for that are attention, process and not knowing the check is there;
a first-time-contributor approval nobody clicked looks exactly like this in the
data.

The value of the figure is therefore comparative, which is the argument for
measuring it **before** anything changes rather than after. On its own it is a
starting line. Re-run over the same corpus once contributing is possible, the
same join is what turns "contribution is being checked more" from an assertion
into a difference between two numbers derived the same way. A baseline nobody
took is the one thing no later sweep can reconstruct.

The join also produces a check on the classifier rather than on the corpus: two
fork pull requests **passed** on repositories the classifier placed outside the
pull-request-triggered subset. An observed pass where the classification says
no pull request triggers anything is a contradiction, and the classifier is the
likelier party to be wrong: a trigger shape its reader missed, or a check
posted by something it does not read. Two cases is not a crisis; it is the
kind of discrepancy only ground truth can surface, and it is why this entry
exists.

This is why the tool reports the contribution question first, ahead of any CI
figure, and states plainly when there is nothing to validate against.

The method is also GitHub-only, because the rule it rests on is GitHub's.

**What it led to.** A separate entry point rather than a feature of the
classifier, joined to a *named* profile so a reader can see which reading's
classes are being validated. And the counts that make the absence legible:
total pull requests, fork pull requests, and fork pull requests from a fork
someone else owns, because an in-house fork-and-pull-request workflow sets the
same flag as an outside contributor and must not be counted as one.

**If you are starting fresh.** Look for a place where the platform has already
run your experiment. It is usually cheaper than your classifier and it is
evidence of a different kind. Then look just as hard for the cases where the
observation does not mean what it appears to: both of the traps here were
invisible in the aggregate state, and the thing that actually limited the
method (unchecked pull requests) was not one of the risks anticipated before it
ran.

---

## Check outcome against merge rate, and the restriction it needs

**The question.** A contributor-side run is normally argued for as a
convenience (faster feedback, fewer round trips), and convenience is cheap
to dismiss. The stronger claim would be that showing a contribution passes
the project's own checks changes the contribution's *odds*: that it is more
likely to be looked at and merged than one whose status nobody knows. If that
holds, supplying the signal is not a courtesy to the contributor but a change
to whether the contribution gets attention at all. Is there anything already
measured that speaks to it?

**What was done.** Nothing was fetched. The fork-observation sweep already
records, for every fork pull request, both its check outcome and its state, so
the join costs nothing: merge rate by check outcome. The one necessary
restriction is to repositories that have a pull-request-triggered pipeline,
because everywhere else "no check ran" only means there was no pipeline to run
one.

**Measured effect**, over fork pull requests to repositories with a
pull-request-triggered pipeline:

| check outcome | fork PRs | merged |
| --- | ---: | ---: |
| passed | 42 | 85.7% |
| no check run | 264 | 64.0% |
| failed | 20 | 45.0% |

**That restriction is part of the finding and not a tidying step, because
without it the result changes sign.** Across *all* fork pull requests,
unrestricted, the 1853 with no check merged at 83.6%, above the 81.8% of the
44 that passed, which reads as a check making no difference or hurting. That
is the first figure an adversarial reader will compute, and it is the right
one to reach for. It dissolves on inspection: it is dominated by the 1494 pull
requests to repositories with no pipeline at all, a different population
answering a different question. The ordering in the table above exists only
inside the join, and an entry that quoted it without the join would be
quoting an artefact.

**Limitation that remains.** It is correlation, and two confounders are plain
enough to name rather than wait to be asked about. A maintainer who bothers to
operate the check is plausibly also one who bothers to review, which would
make the outcome a proxy for attentiveness rather than a cause of anything.
And a contributor who gets the check passing is plausibly writing a more
mergeable change, which would make the pass a symptom of quality. Neither
direction of causation is established here, and the data cannot establish it.

Nor is the passing arm large: n=42 puts roughly ±11 points around 85.7%, wide
enough that the gap to the no-check row is suggestive and not settled. The
failed-versus-no-check contrast rests on larger numbers and is the firmer
half, which is fortunate, because it is also the more useful one.

**What it led to.** The bottom row is the corroboration worth keeping, not the
top one. A failing check predicting non-merge means checks are **acted on
where they exist**, rather than posted and ignored; and the previous entry's
finding (that four fork pull requests in five to a repository that checks
pull requests carried no check) is about a gate that was never operated. Put
together, the two say the gate works when it is operated and is mostly not
operated, which is an argument for a run that does not need anybody on the
maintaining side to act first. That argument is about attention, and it is a
different and sturdier one than asking for faster feedback.

**If you are starting fresh.** When a sweep has been built for one question,
check what *other* question its stored fields already answer before collecting
anything; this join was free and is more consequential than the measurement it
came from. Then compute the unrestricted version of your own headline figure
before publishing, because a critic will. And if the unrestricted version
disagrees, the restriction has to be argued for in the text rather than
applied in the code. What would settle the causal question is not a better
join but a before-and-after: merge rates by outcome over the same corpus,
measured again once a contributor-side signal is actually available. That is
the same reason the baseline in the previous entry was worth taking early.

---

## Differential execution, running the pipeline with nothing granted

**The question.** Every other entry here reads pipeline text, and the two
entries above it end in the same place: the information wanted is not in the
file. The purpose of a credential is not written down, and neither, more often,
is the name of the command that runs the tests. **Execution does not have to
find it.** Run the pull-request workflow with no secret supplied and watch:
whether the tests are behind a project shell script, a `make` target, a
`./gradlew build` or a devenv wrapper stops mattering, because the pipeline
reaches them without any rule knowing they are there. This was listed under
"approaches not tried" with the assessment that it was the right answer to the
question and the wrong cost and consent model for an unsolicited survey. That
assessment stands; what changed is that it was built as a small, named,
opt-in-shaped instrument rather than as a measurement sweep, and run on eight
repositories to see what it could decide.

**The measured outcome is deliberately not a green run.** This is the design
decision the rest of it hangs on. Most pipelines fail under a local runner for
reasons that have nothing to do with privilege, so a green workflow would be a
measurement of the runner. The question asked instead is whether the check
**executed**, with nothing granted, without failing for a secret-related
reason. If the project's own commands ran at all while nothing was granted,
nothing granted was blocking them, whatever became of the rest of the run.

**What was done.** Six outcomes, three of which answer the question and three
of which are excluded from every share:

- `ran-unprivileged`: every step ran and the job exited zero;
- `ran-with-failures`: a project command executed and failed on its own merits;
- `secret-required`: the failing step's own output names a missing, empty or
  rejected credential;
- `environment-failure`, `timed-out`, `not-attempted`: **proves nothing**.

**The positive case is not a heuristic and the failure cases are.** That
asymmetry is the whole of why this is reportable. `ran-unprivileged` rests on
an absence enforced by construction rather than detected: no secret file is
read, no secret is passed, credential-shaped variables are taken out of the
runner's environment, so nothing could have consumed a secret. Every other
class is a reading of log text, and **an unrecognised failure falls to
`environment-failure`**, which supports no claim in either direction. A failure
is read as `secret-required` only when the *failing step's own output* says so,
and as `ran-with-failures` only when a positive signature of a check reaching a
verdict matched. Ambiguity therefore costs a reading and never buys one, in
either direction, which is the same asymmetry the credentials axis and the
test-step determination hold to.

Three details of the mechanism turned out to be load-bearing, and each was
found by running it rather than by reasoning about it.

**The credential table is matched against one step, not the log.** Matching the
whole log was the obvious first shape and it is wrong in the one direction that
matters: a local runner with no cache service emits credential-looking warnings
twice per workflow, in steps that succeed, so every green run in the corpus
would have read as needing a secret.

**The runner's own inability is consulted first.** A local runner fetches
actions from a public API unauthenticated, so its rate-limit rejection reads
exactly like a project's missing token if the credential table is asked first.

**The log format has to be read off the output.** The runner's result line
carries a step duration its start line does not, so pairing a result with its
step by name fails silently unless the duration is stripped. Leave it on and no
step is ever paired, every run looks like one where nothing finished, and the
whole corpus reads as an environment failure. A defect that turns a green
distribution into an all-failures one looks exactly like a finding.

**And a budget that runs out has to take the container with it.** Killing the
runner outright leaves the container it was managing running, and that
container then consumes the host while the *next* repository runs, so one
timeout would quietly measure everything after it under contention. The runner
is therefore started in a session of its own and the session is asked to stop
before it is made to. Which brings its own trap, found the way these are
usually found: the group signal is correct only because of that session, and a
mutation test that removed it signalled the harness's own group and killed the
run. There is now a guard against signalling the group the code is running in,
and the check for it runs the scenario in a child, because a check cannot
report a failure from inside a process it has just killed.

**Measured effect: it answered half of a sample chosen for being answerable,
and every answer went the same way.** Eight repositories, all drawn from the
band static reading could not resolve, all of them carrying
`test-step-unidentified`:

| outcome | repositories |
| --- | ---: |
| ran-unprivileged | 3 |
| ran-with-failures | 1 |
| secret-required | 0 |
| **environment-failure** | **4** |
| timed-out | 0 |
| not-attempted | 0 |

So **four of eight now have an answer, and all four are in the same direction**:
the pull-request check ran with nothing granted. None needed a credential. The
single most useful case is the `ran-with-failures` one, because it is the band's
central case resolved: the configuration names no test command, the tests sit
behind a build target, and the run shows a suite of seventeen tests executing
and eleven of them failing, with no secret present. **Execution supplied the
evidence the configuration withheld**, which is exactly what reading could not
do and exactly why the three largest `unidentified` buckets in the entry above
are the sample this had to cover.

**The cost, which is the reason it is not a sweep.** 16.7 minutes across eight
repositories, clone included and pacing between them excluded: a mean of 125
seconds each, from 6.5 seconds for one that failed at its first step to 303
seconds for a JVM build that ran its suite. On an ARM host the runner images
are amd64 and run under emulation,
which dominates that figure, and the first repository of a corpus also pays for
the image pull, measured separately at about four minutes. That is two to three
orders of magnitude more expensive per repository than reading the text, and it
is the floor rather than the average, because the sample was chosen for small
workflows and recognised toolchains.

**What the selection rule costs, stated because it is severe.** From the 361 of
1428 classified repositories with a pull-request-triggered pipeline, dropping
those static reading already resolved leaves the unresolved band; of that band,
the filters for what a local runner can execute leave fewer than a third:

| dropped by | repositories |
| --- | ---: |
| resolved by static reading | 88 |
| no recognised toolchain, so a failure would not be interpretable | 123 |
| not entirely in the one pipeline grammar the runner reads | 35 |
| asks for an environment the runner cannot provide | 17 |
| `special-env` in either scope | 17 |
| a second repository from one owner | 9 |

**This is not a sample of the corpus and nothing from it extrapolates.** The
rule selects for what a local runner can execute and for cases where a failure
could be read, which is a selection on precisely the properties under
measurement. The per-repository outcomes are the result; the distribution is
not.

**Limitation that remains.** Four of the eight proved nothing, in a sample
chosen for being runnable, and the causes are instructive: a package manager
the runner image does not carry, a headless browser binary absent from it, a
language's refusal to install into a system environment, and a container
orchestration command that was missing because **this harness deliberately
withholds the host's container daemon from the workflow container**. That last
one is a design choice paying for itself in the honest direction: the runner
mounts the daemon's socket by default, which hands a third-party pipeline
control of the daemon running it, and an honest "proves nothing" is the right
price for not doing that.

Three of those four reached `environment-failure` through the fall-through
rather than through a named pattern. The outcome is right either way, by
construction, but the *reason* recorded is then only "this recognises nothing
here", so the named environment table is thinner than a corpus of this shape
needs. That is the cheapest available improvement and it changes no outcome.

The two structural limits are harder. The runner reads one pipeline grammar,
which is a selection constraint and not a fixable gap. And a runner older than
the enforced floor refuses every action built on a modern Node runtime, so a
corpus measured with one would report an environment failure almost everywhere
and the distribution would read as a finding; the floor is checked rather than
documented for that reason, and the newest runner on PATH is the one used, so
that PATH order does not decide what the measurement says.

**And the consent question is unchanged.** This executes code its maintainers
wrote for infrastructure they chose, in an environment they did not pick. That
is why the sample size has no default in any spelling, why there is a low
ceiling above it, and why the plan is printed before anything runs. The
instrument is the right shape for a project pointing it at its own
repositories, or for maintainers opting in. It is not the right shape for a
survey, and building it has not changed that.

**What it led to.** It is kept, as the only per-repository claim in this
repository worth quoting, and `ciprofile.differential` is where it lives. Four
repositories whose pipelines demonstrably run with nothing granted is a
stronger statement than anything the static side produces about them, and it
was produced for cases the static side had given up on. It is kept small: a
named handful, with the selection rule and its caveat travelling in the output
file beside the outcomes.

**If you are starting fresh.** Build this, and make the measured outcome
"did it execute" rather than "did it pass" before you write a line of it;
the second question measures your runner and will waste the whole exercise.
Then decide, on paper, which class an unrecognised failure falls into, because
that single decision determines whether the instrument under-claims or
flatters, and it is very hard to change afterwards. And read your runner's
actual log output before writing anything that parses it. Two of the three
defects that cost real time here were differences between what the runner
prints and what its documentation says it prints.

---

## A destructive test

**The question.** Does the "never overwrite the corpus files" guard actually
fire?

**What was done.** A check proved it by aiming a real write at the real output
file and asserting that the guard refused. Correct, and it passed, for as long
as the guard held.

**Measured effect.** The mutation test then disabled the guard (which is the
whole point of a mutation test), and the write landed. It destroyed a derived
output file that had cost an hour and a half of paced requests to produce.

**Limitation that remains.** None, once the shape is fixed: the guard refuses by
**basename**, not by full path, so every test write can aim at a scratch
directory and still prove the property. A broken guard then spills into a
temporary file nobody cares about.

**What it led to.** A rule stated in CONTRIBUTING.md: **a test that can destroy
data is a bug in the test**. Mutation testing is what makes that more than
tidiness: it deliberately breaks the thing the test is pointing at, so any
test whose safety depends on the code under test being correct is a loaded gun.

**If you are starting fresh.** Write the guard so that proving it needs no
dangerous target. If you cannot, you have found an argument for changing the
guard, not for being careful with the test.

---

## Approaches not tried

With an assessment of each, so the next person can disagree with the
assessment rather than rediscover the option.

### A graph representation of step-to-privilege edges

Instead of hand-rolled attribution ("which step is this grant for?", answered
with an ordered set of rules and a frame), build a graph: steps as nodes,
privileges as nodes, edges for every way a privilege reaches a step (`env:`,
`with:`, a job-level block, a `permissions:` grant, an output passed between
steps). The questions this tool asks become queries over that graph, and
attribution stops being a special case.

The attraction is that the attribution logic is currently the most intricate
part of the codebase and the place where the subtlest defects have lived
(the unattributable-privilege reading, the unused-grant reading, the frame).
The doubt is that the hard part may not be the representation: the measured
failure in that area came from *not seeing the steps at all*, which a graph
would have inherited, and the central negative result above is about
information that is not in the file in any representation.

**Assessment: likely a real improvement to maintainability and to
cross-grammar reuse, unlikely to move a figure.** Worth doing if the rule set
grows, or if a third grammar (Azure Pipelines, Woodpecker, Drone) is added.
That is the point where three sets of hand-rolled attribution stop being
affordable.

### Inverting the question: what a standard runner image would have to carry

This tool asks "what does each pipeline need?". The inverse is "what would one
shared runner image, offered to everybody, have to carry before N% of these
pipelines ran on it?" That is a question about capacity rather than about
trust, and the `assumes-toolchain` signals already collect the raw material
(`toolchain-node`, `toolchain-python`, `toolchain-image`, the runner labels).

It is attractive because it is **actionable in a way the privilege question is
not**: a host can act on "this image needs node, python and a JVM" and cannot
act on "43% of these pipelines need a secret for reasons nobody wrote down". It
is also a much easier measurement, since what a job declares about its
environment is far more explicit than what it declares about its purpose.

**Assessment: the most promising unexplored direction, and cheap.** The signals
are already collected and unused except as a tally; turning them into a
distribution over images and labels is a small piece of work with a clear
reader.

### Asking the maintainers

A survey. For a long tail of small projects this is hopeless, but corpora of
this kind are usually concentrated: a small number of publishers account for
most of the repositories. For those, asking directly ("does this pipeline need
a secret to run its tests, and what for?") gives an **authoritative** answer to
exactly the question static analysis cannot reach, and it takes a handful of
conversations rather than a classifier.

The cost is that it does not scale, it cannot be re-run cheaply when the corpus
moves, and the answers are not independently checkable. But it would settle the
155 unclear cases of the 361, and it would do so with the only evidence that
actually exists for them.

**Assessment: the correct instrument for the specific question this tool
failed at.** The right shape is probably both: static analysis to find the
cases that are unclear, and a survey of the few publishers who own most of
them.
