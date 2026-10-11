# <corpus name>, <month year>

One or two sentences: whose question this run was answering, and whether it
answered it.

Copy this file to `runs/<YYYY-MM>-<corpus-slug>.md` and fill it in. Delete the
guidance in brackets as you go, keep the headings. [README.md](README.md) says
what each descriptor field prevents; the one-clause reminders below are not the
whole argument.

## Descriptor

[Every field present, one line each, in this order. `unknown` and `n/a` are
answers; a blank is not. Anything needing a sentence goes under "Notes on the
descriptor" below, not inside a value.]

```
corpus:        [one line naming the population]
selection:     [how chosen; "every repository on the instance" is an answer]
repositories:  [how many were read]
denominator:   [how many every share is over, and what left it]
forge:         [the platform they were read from]
adapter:       [forgejo | gitlab | github | local]
mirrors:       [yes | no | unknown]
fetched:       [YYYY-MM-DD | unknown]
analysed:      [YYYY-MM-DD | unknown]
from-cache:    [yes | no]
tool-commit:   [the commit that produced the figures, or what did instead]
yaml-parser:   [yes | no | unknown]
partial:       [no, or what was left out]
cap:           [n/a, or the cap and how many repositories it bit]
unreadable:    [how many could not be read]
```

| field | why it is there |
| --- | --- |
| `corpus` | a population named rather than implied |
| `selection` | a prefix or a first-N is not a sample |
| `repositories` | the count read, which is not the count shares are over |
| `denominator` | two readings of one profile differed only in what they counted |
| `forge` | the platform read is not always the platform being discussed |
| `adapter` | each adapter sees something different, and says so in `limitations` |
| `mirrors` | a corpus of mirrors measures the upstreams' pipelines, not load where the mirrors sit |
| `fetched` | every figure describes the corpus on this date and no other |
| `analysed` | rule changes move figures, so the later date is what dates the rules |
| `from-cache` | otherwise a months-old corpus passes for a fresh measurement |
| `tool-commit` | the same corpus gave three different distributions across three rule revisions |
| `yaml-parser` | the two structural readings are not identical |
| `partial` | a distribution over an unannounced subset will be quoted |
| `cap` | a cap censors counts, and in a knowable direction |
| `unreadable` | an unreadable repository must never be counted as `no-pipeline` |

## Notes on the descriptor

[Prose for whatever a one-line value could not carry: which direction a cap
censors in, why the denominator is smaller than the repository count, what the
tool commit was if it was not a commit here. One sub-heading per field that
needs one. Delete the ones that do not.]

### What the adapter could not see

[Anything the adapter could not read, including whatever its own `limitations`
field said. Those sentences are the only place a reader meets them.]

## Figures

[Recomputed from your own output, not copied from a terminal. Give each
distribution its denominator in the heading or the caption, and make every
sub-table add up to a total you state.]

### Pull-request scope

| class | repositories |
| --- | ---: |
| acts-on-forge | |
| writes-outward | |
| read-credential | |
| special-env | |
| self-contained | |
| no-pull-request-trigger | |
| no-pipeline | |
| **total** | |

[Repositories with a pipeline a pull request triggers: the sum of the first
five rows. State it, because every share below is over it rather than over the
denominator.]

### Repository scope

[The same table. It describes what each project needs overall and is not the
figure for the contributor question.]

### Reported beside the class

[The forge-token split, `assumes-toolchain`, `uses-pull-request-target`,
`thin-wrapper`, the credentials axis, `other_ci`. The forge-token split matters
most: it is the number that lets a sceptic restate your headline under a
stricter reading without re-running anything.]

### Anything else this run measured

[A fork observation, a cross-scope comparison, a join against something else.
If a figure only holds under a restriction, put the restriction in the same
sentence as the figure, and give the unrestricted version too. Name the key any
join was made on.]

## Quotable, and not

| Figure | Quotable? |
| --- | --- |
| | |

[Your own corpus, not a copy of the tool's table. The rows worth having are the
ones where the answer is no, or yes with a condition.]

## What this run cannot answer

[The questions this corpus looks like it answers and does not. This section is
the reason a result over an unmeasurable corpus is still worth submitting.]

## Disagreements

[Any figure here that conflicts with one written elsewhere in this repository,
stated and left unresolved rather than silently reconciled. Delete the heading
if there are none.]
