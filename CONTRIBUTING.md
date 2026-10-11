# Contributing

The code here holds to a short list of rules. They are not style preferences;
each of them is a defect that happened, and [EXPERIMENTS.md](EXPERIMENTS.md)
says which.

## Reading the code

| | |
| --- | --- |
| `ciprofile/structure.py` | Where pipelines live; cutting their text into the units a rule asks of, and into the scopes a unit inherits from |
| `ciprofile/rules.py` | The signal tables, and what a privilege is for |
| `ciprofile/classify.py` | The two scopes, the ladder, the derived figures |
| `ciprofile/sweep.py` | Discovery, and what a failure means |
| `ciprofile/cache.py` | The evidence cache, and refusing to misread one |
| `ciprofile/report.py` | The profile JSON and the printed summary |
| `ciprofile/differential.py` | Running the pipeline with nothing granted; the guards that make it safe to, and what a failure is allowed to be read as |
| `ciprofile/sources/` | One adapter per forge, behind one interface |
| `fixtures/ci/` | Synthetic repositories and the table they must classify as |

Each module's docstring carries the argument for what it does, including the
cases where a rule is deliberately wrong in one direction.

## The discipline

**Read-only, by construction.** Every adapter issues GET and nothing else.
There is one transport and it has no method parameter, so no call site can turn
a read into a write. This is what makes it acceptable to point the tool at a
platform somebody else operates and to leave it running. The test suite asserts
it from the source rather than trusting it, because one `method=` argument is
all it would take.

**Paced, with a per-adapter floor.** The gap between requests is enforced in
the transport, not at the call sites, so no caller can forget it. It can be
configured gentler and never sharper: a knob that can be set to zero is a knob
that will be. The floors differ on purpose: an instance you operate and can
watch is not the same as somebody else's production platform whose limits you
cannot read, so the GitLab and GitHub floors are twice the Forgejo one.

**One worker by default.** Pacing happens inside the worker, so the worker
count *is* the request rate. Two is the ceiling where the host is yours, and
there is no concurrency at all against a host that is not.

**Under-claim on failure.** A repository that could not be read is recorded as
unknown with the reason and excluded from every count. It is never counted as
`no-pipeline`, which would turn a transient 503 into evidence of an absent
pipeline and inflate the one figure most likely to be quoted. Wherever a rule
has to guess, it guesses in the direction that keeps a privilege *visible*
rather than the direction that flatters the headline.

**Refuse rather than produce a partial corpus quietly.** A distribution over an
unannounced subset is the one output worth less than no output, because nothing
about it looks wrong, and it will be quoted. Where a run is partial, every
output says so, in the file as well as in the terminal, because the terminal
scrolls away and the file is what somebody finds later.

**Every rule change comes with a fixture.** `fixtures/ci/` holds one synthetic
repository per case and `expected.txt` says what each must classify as, in both
scopes. A rule whose real effect is a distribution over somebody else's corpus
has no other diff; the fixture table is what makes the blast radius of a change
visible in a review.

**Every heuristic states its error direction.** In the comment next to it:
which way it is wrong when it is wrong, and what that costs. "This can
over-claim, which pushes a repository up the ladder" is a usable statement;
"this is approximate" is not. New rules are held to it.

**Capture the decision, not its evolution.** Comments justify the current
design on its merits. The history of how it got there belongs in
EXPERIMENTS.md, where it is useful, rather than scattered through the code as
"originally X, now Y".

## Running the tests

```sh
./test.sh
```

No network, no credential, no host, nothing installed. Every test file takes
the socket layer away before it does anything, so a stub that quietly fell
through to a real forge fails there rather than spending somebody's rate budget
from a test run. `PY=/path/to/python ./test.sh` runs it against another
interpreter, which is worth doing once with PyYAML installed and once without,
since the structural reading has two implementations and the suite asserts they
agree.

## Mutation-test the checks

**This is the habit most worth keeping.** Several of the checks here were
vacuous until somebody broke the thing they claimed to test and watched them
pass anyway. The procedure is cheap: comment out the rule, run `./test.sh`, and
if nothing goes red the check is decoration. Put the rule back.

These are worth re-running after any substantial change, because they are the
ones whose failure is invisible in the output:

| Mutate | A check that must go red |
| --- | --- |
| Reverse the two tests in `credentials_purpose()` so reporting wins over unclear | the asymmetry checks in `tests/test_axis.py` |
| Reverse the two tests in `test_step_privilege()` so clean wins over privileged | "an undeterminable scope is privileged, never clean" |
| Stop reading the enclosing scope in `test_step_signals()` | "an inherited credential is available to the test step", and the fixture table |
| Make `units_with_scope()` hand back the whole-file frame instead of per-step scopes | "a credential in another job does not reach this one" |
| Make `empty_verdict()` read "the source did not say" as empty | "an unreadable repository is unknown, never no-pipeline" |
| Stop consulting the `push:` input of the build-and-push action | "a conditional push: input is still a push", and the fixture table |
| Make the line reader refuse a sequence at its key's own column | "a steps: block at its own column still yields steps" |
| Drop the missing-sample or the ceiling refusal in `require_sample()` | "--sample is required, with no default", "a sample above the ceiling is refused" |
| Point the differential runner's `--secret-file` at `.secrets`, or drop the flag | "the runner is never given a secret, default file included" |
| Stop scrubbing credential-shaped variables in `scrubbed_env()` | "credential-shaped variables leave the environment" |
| Leave the duration suffix on the runner's result line in `STEP_RESULT` | "the real log format is what is parsed" |
| Match the credential table against the whole log instead of the failing step | "a credential warning in another step does not convict" |
| Consult the credential table before `RUNNER_LIMIT` in `classify_outcome()` | "the runner's own inability outranks the credential table" |
| Make the fall-through in `classify_outcome()` read as having executed | "an unrecognised failure claims nothing" |
| Lower `RUNNER_MIN`, or take the first runner on PATH rather than the newest | "a runner too old to run the corpus is refused", "the newest runner on PATH wins" |
| Signal the runner alone rather than its process group on a timeout, or stop asking the session to stop at all, or start it in this session | "a budget that runs out takes the whole session with it", "run_workflow stops the session when the budget runs out" |
| Drop the refusal in `_stop_session()` to signal the group it is running in | "stopping never signals the group it is running in" |
| Let `IMAGE_LIMITATION` claim the daemon's own free space again, or drop `HEADROOM_LIMITATION` from the refusal | "the daemon's own figure is preferred to the host's", "the disk preflight refuses below the floor" |
| Admit a container-launching command to `DOCKER_READ_ONLY`, for the better disk figure | "nothing here prunes anything, asserted from the source" |

One rule follows from mutation testing and is not negotiable: **a test that can
destroy data is a bug in the test.** Mutation testing deliberately breaks the
code a test points at, so any test whose safety depends on that code being
correct is a loaded gun. The output-file guard refuses by *basename* precisely
so that every test write can aim at a scratch directory and still prove the
property. [EXPERIMENTS.md](EXPERIMENTS.md#a-destructive-test) records what
happened before it did.

## Adding a forge

Implement the four methods in `ciprofile/sources/base.py` and nothing else;
the classifier is forge-agnostic once it has `{path: text}`. The method that
needs thought is `is_empty()`, because distinguishing "no pipeline" from "could
not read" is load-bearing and the forges expose it differently. Three answers:
`True`, `False`, `None`, and `None` is not "not empty". If your forge cannot
answer, say `None` and document the proxy you considered and rejected, as the
GitLab adapter does.

Set `PACE_FLOOR` and `WORKER_CEILING` deliberately, and write the argument for
them in the module docstring. Put whatever the adapter cannot see into
`limitations`; those sentences travel into the output beside the figures they
bear on, which is the only place a reader will meet them.

## Adding a signal

In `ciprofile/rules.py`, in the table it belongs to. With it:

- a fixture, and a row in `expected.txt`;
- a comment saying what the signal is evidence *of*, and which way it is wrong;
- if it is an exception list rather than a pattern, a check that every entry
  would otherwise have been matched, because a dead entry reads as a decision
  nothing is enforcing.

Prefer an exception list over a cleverer regex. The list is readable,
checkable and extensible by anybody; a regex whose judgement is unreadable
is not.
