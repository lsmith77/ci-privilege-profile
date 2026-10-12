# Mirrored public-administration repositories, October 2026

The corpus this tool was built against, and the run its figures come from. It
answers what privilege a contributor's pull request would need across a body of
public-sector code, and it cannot answer what those pipelines would cost the
platform holding them, because every repository in it is a mirror whose
pipelines have never run there.

## Descriptor

```
corpus:        Swiss public-administration repositories, mirrored onto one Forgejo instance
selection:     every repository the instance holds; no limit, no sample, no ordering
repositories:  1432 candidates, 1428 classified
denominator:   1409; 4 unreadable and 19 organisation profile repositories left it
forge:         one self-hosted Forgejo instance, a mirror platform only
adapter:       forgejo; the fork observation reads GitHub's GraphQL API instead
mirrors:       yes, upstreams overwhelmingly on GitHub
fetched:       2026-10-10
analysed:      2026-10-10
from-cache:    yes
tool-commit:   not a commit of this repository, see below
yaml-parser:   no, the line reader produced these figures
partial:       no
cap:           fork observation, newest 100 pull requests per repository, bit on 92
unreadable:    4
```

## Notes on the descriptor

These are the facts a one-line value could not carry.

### The corpus and the platform

The repositories are published by public-administration bodies, predominantly
Swiss federal, cantonal and municipal: organisations that release software
without being software vendors. The platform is a mirror platform only.
Registration is not open and contribution on the platform itself is not
possible, which is why the fork observation reads the upstreams instead. A small
minority of upstreams are on GitLab rather than GitHub.

### The denominator

The instance yielded 1432 candidates. 4 could not be read and are excluded from
every count. Of the 1428 classified, 19 are organisation profile repositories
(`.github` and friends) and leave the denominator, giving 1409. Both readings
are reported below, because the profile file's own top-level tallies are
computed over all 1428.

### The two dates

Fetch and analysis are both 2026-10-10, which is exactly why they have to be
separate fields: a re-analysis next month would carry the same fetch date and
would still describe this corpus and not the one standing then. The cache
arrived in two segments, both of that date.

### The cap, and the direction it censors

The fork observation examined the newest 100 pull requests per repository by
creation date. The cap bit on 92 repositories, 45 of which have at least one
fork pull request and 28 of which are in the pull-request-triggered subset.
Fork counts for those are censored **downward**: an older fork pull request
cannot be ruled out.

### Completeness, and the unreadable repositories

The profile and its cache both record themselves as complete. Nothing was left
out beyond the 4 repositories that could not be read, and those are excluded
from every count rather than counted as `no-pipeline`.

Of the 4, two answered HTTP 404 on the root listing while the instance reported
the repository as not empty, which is how an unborn or missing default branch
reads on a mirror whose initial sync failed. Two answered with a transport
failure.

### The tool commit field, and why this run is the argument for it

These figures were produced by the predecessor implementation this repository
was extracted from, and the output files name it: `classify_ci.py` for the
privilege profile and `fork_contribution.py` for the fork observation. The
extracted tool was then verified to reproduce the profile exactly, with zero of
1428 repositories differing. That verification is worth having and it is not
the same claim as "the committed code produced these numbers", so the field
records what did.

The distinction is not pedantry. The same corpus produced three different
privilege distributions across three rule revisions during development, and a
figure here is only comparable with a figure elsewhere if both say which rules
were in force.

### What the adapter could not see

The privilege profile is signal detection over pipeline text, read through the
instance's own contents API. It reads `.forgejo/workflows/`,
`.gitea/workflows/`, `.github/workflows/` and `.gitlab-ci.yml`, and nothing
else; CI definitions at the repository root belonging to other systems are
counted separately as `other_ci` and are not read.

Because the repositories are mirrors, the Forgejo instance's own view of them is
a copy. Any divergence between a mirror and its upstream at fetch time is
invisible here, and the fork observation, which reads the upstreams directly, is
the only part of this run that saw the originals.

The structural reading was the indentation-based line reader, since no YAML
parser was installed. `EXPERIMENTS.md` records that over this same corpus the
two readings disagree about exactly one repository, in the over-claiming
direction: a flow sequence written on the line after `on:` is undeterminable to
the line reader, which keeps the file in the pull-request scope, and plain to
the parser, which takes it out. That cross-reference is not recomputed here.

## Figures

All recomputed from the profile and the fork observation. The class name the
profile writes for self-contained is `autark`; it is spelled out below.

### Pull-request scope, over 1409 repositories

What a contributor's own pull request would set off. This is the scope the tool
exists to produce.

| class | repositories |
| --- | ---: |
| acts-on-forge | 70 |
| writes-outward | 67 |
| read-credential | 47 |
| special-env | 16 |
| self-contained | 158 |
| no-pull-request-trigger | 187 |
| no-pipeline | 864 |
| **total** | **1409** |

**Repositories with a pipeline a pull request triggers: 358**, the sum of the
first five rows. Every share in the credentials axis below is over 358 and not
over 1409.

The two absences are the larger half of this corpus and they are different
things. 864 repositories hold no pipeline this tool reads at all; a further 187
hold pipelines that no pull request sets off, which is a project that does CI
under conditions a contributor does not meet.

### Repository scope, over 1409 repositories

What each project needs overall, a maintainer's release workflow included. Not
the figure for the contributor question.

| class | repositories |
| --- | ---: |
| acts-on-forge | 149 |
| writes-outward | 206 |
| read-credential | 86 |
| special-env | 13 |
| self-contained | 91 |
| no-pipeline | 864 |
| **total** | **1409** |

Scoping to what a pull request triggers moves self-contained from 91 to 158 and
`writes-outward` from 206 to 67. The scope split is the single largest effect
measured over this corpus.

### Reported beside the class, pull-request scope

| aside | repositories |
| --- | ---: |
| `uses-forge-token` | 95 |
| …of which also carry a forge-write signal, so `acts-on-forge` on their own evidence | 31 |
| …**of which carry no forge-write signal at all** | **64** |
| `assumes-toolchain` | 203 |
| `special-env` as a flag rather than as the primary class | 28 |
| `thin-wrapper` | 12 |
| `uses-pull-request-target` | 5 |

The 64 is the load-bearing number: those repositories' class rests entirely on
the judgement that a forge-minted token is not a credential a contributor has
to supply. Anybody who rejects that judgement can restate the distribution
under the stricter reading from this row alone.

`other_ci` markers at the repository root, which `no-pipeline` must be read
beside: 74 repositories carry at least one, 79 markers in all.

| marker | repositories |
| --- | ---: |
| `.travis.yml` | 41 |
| `Jenkinsfile` | 29 |
| `.circleci` | 4 |
| `appveyor.yml` | 4 |
| `.woodpecker.yml` | 1 |

### The credentials axis, over the 358

What each scope's privilege is **for**, which is the question the tool is worst
at.

| reading | repositories |
| --- | ---: |
| self-contained: needs nothing granted as written | 158 |
| reporting-only: privilege is entirely a record of the run | 24 |
| test-time: the credential is what makes the tests possible | 6 |
| **unclear: one privileged step recognised as neither** | **152** |
| no credentials flag and not self-contained | 18 |
| **total** | **358** |

The last row is 16 repositories whose only privilege is a special runner and 2
whose forge interaction carries no credential for the axis to classify.

The derived figure is therefore that **between 50.8% and 93.3%** of
repositories with a pull-request pipeline could have their checks run by a
contributor (182 of 358 to 334 of 358). The band is too wide to use, and that
is the finding rather than a defect to be fixed: in the unclear cases the
purpose of the privilege is not written down anywhere in the configuration.

### The other denominator, stated so the two readings cannot be confused

Including the 19 organisation profile repositories gives a denominator of 1428
and **361** repositories with a pull-request-triggered pipeline, with
`acts-on-forge` 73, `no-pipeline` 880, `uses-forge-token` 97 split 33 and 64,
`credentials-unclear` 155, and a band of between 50.4% and 93.4%. The profile
file's own top-level tallies are computed over all 1428, which is where 361
comes from. Note that the 64 does not move: the figure the forge-token split
exists for is the same under both readings.

### Fork observation, over the upstreams

GitHub withholds repository secrets from fork pull requests and gives such runs
a read-only token, so a workflow that has ever passed on a fork pull request to
a public repository is proof that it runs without that repository's secrets. A
pass proves something; a failure proves nothing. The method is GitHub-only,
because the rule it rests on is GitHub's.

Coverage, which is why the figures below are over 1340 and not 1409:

| | repositories |
| --- | ---: |
| candidates | 1432 |
| not asked: upstream host could not be determined | 35 |
| not asked: upstream is not on GitHub | 1 |
| **asked** | **1396** |
| unresolved: query unanswered | 50 |
| unresolved: upstream absent | 6 |
| **measured** | **1340** |

Every join below is made on the **profile's own repository key**, which is the
key the fork records are written under, so each repository is matched against
its own classification. 3 of the 1340 have no entry under that key in the
profile's `repos` map, and all 3 are among the 4 that could not be read on the
mirror. The fork records separately carry the upstream's current name, which
differs from the key for 14 of the 1340, 7 of them beyond letter case. 228 of
the 1340 are archived upstream.

| | |
| --- | ---: |
| pull requests reported | 46,012 |
| pull requests examined, under the cap of 100 per repository | 19,007 |
| fork pull requests found | 1,919 |
| …from a fork someone else owns | 1,903 |
| repositories with at least one fork pull request | 253 |
| repositories with at least one external-owner fork pull request | 251 |

| outcome | fork pull requests |
| --- | ---: |
| no checks attached at all | 1,853 |
| passed | 44 |
| failed, which proves nothing | 20 |
| head commit unavailable | 2 |
| pending | 0 |
| **total** | **1,919** |

21 repositories have a passing fork pull request; in 17 of those the pass
carries an Actions check run whose own workflow run was triggered by
`pull_request`, so the repository is **proven** to need no repository secret.
The remaining 4 passed on third-party commit statuses alone, or on a
`pull_request_target` run that holds the base repository's secrets, and are
reported as unproven. The aggregate rollup and the per-pull-request rollup
disagreed nowhere.

So the method yields evidence about **17 of 1340 repositories**. Of those 17,
10 were already classified self-contained in the pull-request scope and the
observation confirms the classifier; **7 were classified as needing some
privilege and were observed running without the repository's secrets**, which
is the classifier over-claiming and is what ground truth is for. In the other
direction, 2 of the 44 passes landed on repositories the classifier placed
outside the pull-request-triggered subset altogether, one as
`no-pull-request-trigger` and one as `no-pipeline`. An observed pass where the
classification says no pull request triggers anything is a contradiction, and
the classifier is the likelier party to be wrong.

### The join, which the unchecked figure cannot be quoted without

The raw count of fork pull requests with no checks is 1,853. **That figure must
not be quoted.** Splitting it on whether the target repository has a
pull-request-triggered pipeline at all:

| | repositories | fork PRs | no checks |
| --- | ---: | ---: | ---: |
| **with** a pull-request-triggered pipeline | 80 | 326 | 264 (81.0%) |
| **without** one | 172 | 1,498 | 1,494 |
| absent from the profile | 1 | 95 | 95 |
| **total** | **253** | **1,919** | **1,853** |

Every column sums to its total. The one on the absent row is `openZH/covid_19`,
which is one of the 4 unreadable and so sits in the profile's `unknown` map
with 95 fork pull requests. It was never classified, so it cannot be placed on
either side of the split.

The quotable figure is **264 of 326**. For the 1,494 there was no pipeline to
attach a check to, and counting those as unchecked would be counting the
absence of CI as a gate nobody opened. What survives the join is still a real
finding, that four in five fork pull requests to a repository which does check
pull requests carried no check, and it is an order of magnitude smaller than
the raw count.

A low figure is the expected reading for this corpus and not a negative result
about the method. These are mirrors of projects developed somewhere else, on a
platform where contributing is not possible at all, so nothing in the setting
could produce high check coverage. The value of the figure is comparative,
which is the argument for taking it before anything changes: a baseline nobody
took is the one thing no later sweep can reconstruct.

### Merge rate by check outcome, same restriction

Over fork pull requests to repositories with a pull-request-triggered pipeline:

| check outcome | fork PRs | merged | merge rate |
| --- | ---: | ---: | ---: |
| passed | 42 | 36 | 85.7% |
| no check run | 264 | 169 | 64.0% |
| failed | 20 | 9 | 45.0% |

**Unrestricted, the ordering inverts.** Across all 1,919 fork pull requests,
the 1,853 with no check merged at 83.6% (1,550 of them) against 81.8% for the
44 that passed, which reads as a check making no difference or hurting. That is
the first figure an adversarial reader will compute and it is dissolved by the
same join: it is dominated by the 1,494 pull requests to repositories with no
pipeline at all, a different population answering a different question.

It is correlation either way. A maintainer who operates the check is plausibly
also one who reviews, and a contributor who gets the check passing is plausibly
writing a more mergeable change. The passing arm is small at n=42. The firmer
half is the bottom row, which rests on larger numbers: a failing check predicts
non-merge, so checks are acted on where they exist.

## Upstream CI activity, fetched 2026-10-12

A later measurement over the same corpus, and the only one here that counts
runs rather than configuration. Two departures from the descriptor above, both
of which bear on how its figures compare with the rest of this write-up.
**It was fetched on 2026-10-12**, two days after everything else, and **its
denominator is the 1428 basis rather than 1409**, because it reads the profile
file directly and that file includes the organisation profile repositories. Its
subset is therefore the 361 repositories with a pull-request-triggered pipeline
on that basis, not the smaller subset the figures above are over.

Of those 361, 323 could be asked of the upstream host's Actions API. 26 hold a
pipeline in a grammar that API cannot answer for and 12 have no upstream host
established; neither group is a zero. On the pull-request event:

| status | repositories |
| --- | ---: |
| passing, newest concluded run inside 30 days | 86 |
| failing, same window | 26 |
| awaiting approval | 5 |
| inconclusive | 2 |
| ran, newest outside the window | 104 |
| never ran | 100 |
| not measured, with reason | 38 |

**100 of 323 declare a pull-request pipeline that has never run once.** Over
every event rather than the pull-request one, only 55 have never run anything,
so the difference is repositories whose CI runs on push and has never been
exercised by a pull request. 119 of 323 ran on the pull-request event inside
the window.

**These runs happened upstream**, on the host each project is developed on, and
not on the mirror platform, which runs no pipeline at all. The reading of a
zero is "this project's pipeline does not run where the project is developed".

It also splits the differential runs' non-answers, which had been one class.
Of the 20 attempts that reached no answer, 10 are pipelines with no upstream
runs either, 4 fail upstream as well, 3 have no run inside the window to
compare against, 1 is undecidable, and **2 rows covering 1 repository** are
cases where the pipeline passes upstream and failed locally. One repository of
this corpus is a demonstrated local-environment failure.

## Quotable, and not

| Figure | Quotable? |
| --- | --- |
| **100 of 323 never ran on the pull-request event** | **Yes**, with the 38 not measured beside it and the word "upstream" in the sentence. It is the figure that qualifies every other one here |
| 55 of 323 never ran on any event | **Yes**, and best quoted next to the 100, since the gap is the finding |
| `passing` 86 | **Only with the 30-day window named.** It describes the newest concluded run, not the pipeline's history |
| 1 repository as a local-environment failure | **Yes**, as a per-repository statement. The 20 non-answers it comes out of are not a distribution |
| The pull-request-scope class distribution over 1409 | **Yes**, as a shape, with the 4 unreadable repositories named beside it |
| `no-pipeline` 864, with `other_ci` 74 beside it | **Yes**, never on its own |
| `uses-pull-request-target` 5 | **Yes**; held strictly to the `on:` declaration |
| The forge-token split 95 / 31 / **64** | **Yes**; the 64 is the point of it |
| `assumes-toolchain` 203 | **Yes**, as a statement about runner capacity, never about privilege |
| Scope split: self-contained 91 to 158, `writes-outward` 206 to 67 | **Yes**; it is an effect size, not a share of any population |
| Contributor-runnable | **Only as "between 50.8% and 93.3%"**. A single number there would be read as a measurement |
| `credentials-unclear` 152 | **As a count of what the tool could not read**, yes. As a property of the corpus, no: it is partly a measure of the rule tables |
| 17 proven of 1340 | **Yes as a floor**, with the reason it is low, which is the corpus and not the method |
| 7 of 17 proven contradicting the classifier | **Yes**, as the direction of the error: the classifier over-claims |
| 264 of 326 fork pull requests unchecked | **Yes, and only with the restriction in the same sentence** |
| Merge rate ordering by check outcome | **Yes, and only with the restriction.** Unrestricted it inverts |
| **1,853 fork pull requests with no checks** | **No.** It counts pull requests to repositories with no pipeline for a check to come from |
| Any single repository's label | **No.** It is a hint. Read its `signals` |
| Anything as a share of "public sector open source" | **No.** This is one mirror set, not a sample of anything |

## What this run cannot answer

**What these pipelines would cost the platform that holds them.** This is the
reading the corpus most invites and least supports. Every repository is a
mirror; every pipeline was written for the upstream's runners and has never
executed on the mirror platform. The distribution says what privilege the
pipelines need, not what load they would place anywhere.

**Whether contribution is being checked more or less than elsewhere.** The
platform does not accept contributions at all, so the fork observation reads
the upstreams and describes practice on GitHub. It is a baseline for this
corpus against itself, not a comparison with any other population.

**What the unclear privilege is for.** 152 of 358 repositories in the
pull-request scope carry a privileged step the rules recognised as neither
reporting nor test-time, and three attempts to narrow that moved the floor by
about a point each. The purpose is not recorded in the configuration, so no
amount of reading the configuration will recover it. Asking the publishers
would; this corpus is concentrated enough for that to be a handful of
conversations.

**Whether a passing check causes a merge.** The merge-rate join is
correlational and the data cannot make it otherwise. What would settle it is
the same measurement again over the same corpus once a contributor-side signal
exists.

## Disagreements

The join every figure above is made on, and the one figure that reads
differently elsewhere in this repository.

**The join key.** Every join between the fork observation and the privilege
profile is made on the profile's own repository key, which is the key the fork
records are written under, so a repository is matched against its own
classification. The committed `ciprofile.fork_observation` joins the same way.
The fork records separately carry the upstream's current name, and a mirror
corpus contains upstreams GitHub has renamed or transferred since the mirror
was taken, so a name-based join is unreliable: it drops every renamed
repository into the absent row, where it is counted as unclassified although it
was classified. `opendata-swiss/metadata.swiss` is such a case. Its fork record
carries `name_with_owner: metadata-swiss/opendata-swiss`, the profile
classifies `opendata-swiss/metadata.swiss` as `acts-on-forge`, and so it
belongs on the with-pipeline row. A join on the current name puts it on the
absent row instead.

**The denominator.** `README.md` and `EXPERIMENTS.md` both describe this corpus
as having 361 repositories with a pull-request-triggered pipeline, and give
`credentials-unclear` as 155. Those are the figures over all 1428 classified
repositories, organisation profile repositories included. This write-up
declares the denominator 1409 and reports 358 and 152. Neither is wrong, and
each figure carries the basis it is over, which is the entire reason that field
is required here.
