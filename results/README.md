# Results

Runs of this tool against real corpora, written up so that somebody who did
not run them can judge them.

**Submissions are welcome and the bar is interpretability, not flattery.** A
result is accepted because a reader can tell what was measured, over what, by
which code, on which date, and which of its figures the submitter is prepared
to stand behind. Nothing here is accepted or rejected on whether its numbers
look good, and **a run on a corpus that turns out to be unmeasurable is a
result worth recording**: the corpus of mirrors in [the seeded
run](runs/2026-10-mirrored-public-administration.md) cannot answer the question
about platform load that it was first pointed at, and saying so is most of what
that write-up is for.

## What goes in here, and what does not

**Not the per-repository output.** `data/` is gitignored on purpose. A sweep's
profile and its evidence cache describe one corpus at one moment and belong to
whoever ran it, and the reason is not tidiness: the per-repository output names
every repository together with the privilege its pipeline appears to need, and
that is a statement about somebody else's project. A submitter may not be free
to publish it even where the corpus is entirely public, and a single
repository's label is a hint and not quotable, so publishing a file of such
labels against named projects publishes the least defensible thing the tool
produces at the largest volume.

**What gets committed is a contextualised write-up**, which is one Markdown
file: the run descriptor below, the figures the submitter computed from their
own output, and a statement of which of those they consider quotable.

**Optionally, an aggregate summary beside it**, as
`runs/<slug>.aggregate.json`, for a figure somebody else may want to read
mechanically. It holds aggregates only. No repository names, no per-repository
rows, nothing from which a per-repository profile can be reconstructed. If a
reader needs the per-repository output, the write-up says enough about the
corpus and the tool commit for them to produce their own.

## Layout

    results/
      README.md                     this file: the format, and the review
      TEMPLATE.md                   copy it, fill it in
      runs/
        <YYYY-MM>-<corpus-slug>.md  one run
        <YYYY-MM>-<corpus-slug>.aggregate.json   optional

One file per run, under `runs/`, and that is deliberate on three counts. A
submission **adds** a file and edits nothing shared, so two submissions in
flight cannot conflict and no reviewer has to arbitrate an index. The directory
listing **is** the index, ordered by the date in the name, so there is no count
of runs maintained anywhere to go stale. And the template sits outside `runs/`,
so a half-filled copy of it is never mistaken for a run.

## The run descriptor

Every write-up opens with this block, before any prose. It is the part that has
to be comparable between runs, and prose is the wrong format for it: two
write-ups cannot be placed side by side if the reader has to find each fact in
a different paragraph.

```
corpus:        one line naming the population
selection:     how the repositories were chosen
repositories:  how many were read
denominator:   how many every share is over, and what left it
forge:         the platform they were read from
adapter:       forgejo | gitlab | github | local
mirrors:       yes | no | unknown
fetched:       YYYY-MM-DD | unknown
analysed:      YYYY-MM-DD | unknown
from-cache:    yes | no
tool-commit:   the commit that produced the figures, or what did instead
yaml-parser:   yes | no | unknown
partial:       no, or what was left out
cap:           n/a, or the cap and how many repositories it bit
unreadable:    how many could not be read
```

Three rules. **Every field is present**, in this order, one line each.
**`unknown` and `n/a` are answers**; a blank line or a missing field is not,
and "not recorded" is a better answer than a guess. **Anything needing a
sentence goes below the block**, under its own heading, not inside a value:
the block stays scannable and the argument stays readable.

Each field earns its line by having been missing once:

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

[EXPERIMENTS.md](../EXPERIMENTS.md) records each of those incidents in full. A
reviewer who knows what a field is for can tell when it has been filled in
uselessly, which is the common case rather than the rare one: "selection: every
repository on the instance" is a real answer, "selection: a representative
sample" is the field left blank in more words.

## Submitting a run

1. Copy [`TEMPLATE.md`](TEMPLATE.md) to `runs/<YYYY-MM>-<corpus-slug>.md`. The
   date is the date the evidence was **fetched**, not the date you wrote it
   up.
2. Fill in every line of the descriptor. See the seeded run, whose
   `tool-commit` says the committed code did not produce the figures.
3. Recompute every figure from your own output rather than copying it out of a
   terminal or an earlier draft. Figures in this project have been
   mistranscribed more than once, and two accounts agreeing has been mistaken
   for confirmation.
4. Say which figures you consider quotable and which you do not. The tool's own
   table is in [USAGE.md](../USAGE.md#which-figures-are-quotable); make the
   same distinction for your corpus rather than presenting every number as
   equally solid.
5. Open a pull request.

## Reviewing a submission

For whoever handles the pull request. None of this requires re-running
anything.

- [ ] **Is the descriptor complete?** Every field present, on one line, with
      `unknown` or `n/a` where it applies. A missing field is the one defect
      that cannot be caught later.
- [ ] **Do the counts sum?** Each class distribution against its stated
      denominator, and each sub-table against its own total. A row that has
      drifted out of a table is the commonest defect here and the easiest to
      catch: the join table in `EXPERIMENTS.md` was published with a row short
      by one repository's worth, then "corrected" into that state a second
      time, because nobody added the columns up. Adding them up is what found
      it.
- [ ] **Does the denominator match the stated corpus?** If the corpus
      description excludes a category, the denominator has to be smaller than
      the repository count by the size of that category, and the write-up has
      to say by how much.
- [ ] **Is the tool commit recorded?** If the figures were produced by
      something other than a commit of this repository, the write-up says so
      rather than naming a commit that merely reproduces them.
- [ ] **Are unquotable figures marked as such?** Any single repository's label,
      anything from a limit or a sample or a partial cache, and any figure the
      submitter has not actually checked.
- [ ] **Is any figure quoted without the restriction it depends on?** This is
      the one that has bitten twice, in both cases by inverting the result
      rather than shading it:
      - the share of fork pull requests that carried no check inverts in
        meaning if the restriction to repositories that **actually run checks**
        is dropped, because the unrestricted count is dominated by pull
        requests to repositories with no pipeline for a check to come from;
      - the merge-rate comparison by check outcome inverts the same way. Under
        the restriction, a passing check goes with the highest merge rate and a
        failing one with the lowest. Unrestricted, having no check at all comes
        out on top, which reads as checks making no difference.

      A figure of this kind is quotable only with its restriction attached, in
      the same sentence. If the submission states the restricted figure, the
      review is to look for the unrestricted one too, because an adversarial
      reader will compute it.

A submission that fails a box is not rejected. It is sent back for the missing
context, which is usually one line.
