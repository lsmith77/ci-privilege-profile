#!/usr/bin/env python3
"""The signal tables: what a pipeline file says it needs, and what it is for.

SIGNAL DETECTION, NOT SEMANTICS
-------------------------------
Everything here is pattern matching over pipeline text plus the light
structural reading structure.py provides. It is therefore wrong in both
directions, and knowing which way matters more than any single rule:

  - A signal can be MISSED. An action no table has heard of, a deploy hidden
    behind a `make release` target, a workflow pulled in by a GitLab
    `include:`, a composite action in another repository, a command assembled
    from variables. Every miss pushes a repository *down* the ladder, toward
    `self-contained`, which is the flattering direction.
  - A signal can be OVER-CLAIMED. The string `docker push` in a disabled job,
    a heredoc or a trailing comment reads the same as a real one; a variable
    whose name ends in `_KEY` reads like a credential whether it is one or not,
    which is what NOT_CREDENTIAL exists to correct. Every over-claim pushes a
    repository *up* the ladder.

So the per-repository answer is a hint, a distribution over a corpus is a
shape, and neither is a measurement. The signal set is recorded per repository
precisely so a reader can re-slice the evidence instead of trusting the label.

Every rule here states its error direction. That is a requirement on new rules
too; see CONTRIBUTING.md.

THE FORGE-MINTED TOKEN
----------------------
`secrets.GITHUB_TOKEN`, `GITEA_TOKEN`, `FORGEJO_TOKEN` and GitLab's
`CI_JOB_TOKEN` are minted by whichever forge runs the job, so a contributor
supplies nothing for them. They are recorded as the `forge-token` signal and
raise `acts-on-forge` only in company with an actual forge-write signal.
Calling them a read credential would tell a reader they need a secret they do
not; ignoring them entirely would hide the forge-write capability. This is the
single judgement here that most moves a headline distribution, which is why
report.py publishes the split rather than leaving it to be taken on trust.

WHAT THE PRIVILEGE IS FOR: REPORTING, OR TEST TIME
--------------------------------------------------
The classes in classify.py say how large a privilege a pipeline needs. They do
not say what it is needed *for*, and that is the more useful thing to know: a
secret, an outward write or a forge call that exists only to record the result
can be dropped and the tests still run, while a pipeline that resolves its
dependencies from a private registry cannot be run without its credential.

So every privileged *step* is read a second time along that one axis. THE
ASYMMETRY IS THE DESIGN RULE. "Reporting-only" is a positive claim about
*every* privileged step in the scope, so every one of them has to be recognised
as reporting before it can be made. A single privileged step that no rule here
recognises forces `credentials-unclear` and can never leave a scope
`reporting-only`. Without that rule the flattering answer would win by
default: anything the tables had not heard of would read as droppable. It is
enforced in one place, credentials_purpose().

The honest finding about this axis is in EXPERIMENTS.md, under "Separating a
secret for the tests from a secret to record the results": the band it produces
is too wide to quote, because in most of the remaining cases the configuration
simply does not say what its privilege is for.

THE TEST STEP ON ITS OWN
------------------------
A narrower question, asked because the one above is answerable so rarely: does
the step that actually invokes the test suite consume a credential? If it does
not, the tests can run without the project's secrets whatever the steps around
them need, which is what a contributor wanting a pre-flight signal is asking.
It is a determination of its own rather than a fourth value on the axis above,
because it is about one step and that axis is about all of them.

Two rules carry it, and both are asymmetries in the same direction as the one
above. A credential the step INHERITS from a workflow-level or job-level
`env:`, or from GitLab's `variables:`, counts as available to it, so the step's
own text is never read alone; and where whether a credential reaches the step
cannot be settled, the step counts as privileged. Test identification is
recognition and not inference: an unrecognised command form answers "not
identifiable" rather than "unprivileged". See test_step_signals().

Its own measured finding is in EXPERIMENTS.md, under "Narrowing the band by
asking only about the test step": it resolves about a third of the unclear
band, and what stops it resolving the rest is no longer an unrecorded purpose
but an unreadable test command.
"""
import re

from .structure import (actions_script_bodies, actions_triggers, kind_of,
                        privilege_units, strip_comments, units_with_scope)

# ---------------------------------------------------------------- the classes
#
# The privilege ladder, most privileged first. Why this order: the first three
# rank by the blast radius of the credential a host actually has to grant. A
# token against the forge API can rewrite the project's own issues, labels and
# releases, and on a shared instance that is the trust decision; an outward
# write can reach a registry, a server or a cloud account, which is somebody
# else's blast radius but not the forge's; a read-only credential is a secret
# that still has to be held and leaked, but grants no write anywhere.
# `special-env` sits below all three because it asks for *capacity*, not trust:
# a Windows, macOS, GPU or self-hosted runner is a bill, and a bill is a
# smaller decision than a permission. `self-contained` is the base case for a
# scope that holds a pipeline file at all, and below it sit the two absences.
NO_PIPELINE = "no-pipeline"
NO_PULL_REQUEST_TRIGGER = "no-pull-request-trigger"
SELF_CONTAINED = "self-contained"
READ_CREDENTIAL = "read-credential"
WRITES_OUTWARD = "writes-outward"
ACTS_ON_FORGE = "acts-on-forge"
SPECIAL_ENV = "special-env"

# Reported beside a class, never as one.
THIN_WRAPPER = "thin-wrapper"
PULL_REQUEST_TARGET = "uses-pull-request-target"
USES_FORGE_TOKEN = "uses-forge-token"
ASSUMES_TOOLCHAIN = "assumes-toolchain"
# The reporting-versus-test-time axis: one of three, mutually exclusive by
# construction, and absent from a scope that needs no privilege at all. A
# question about what the privilege is *for*, never about how large it is, so
# it stays off the ladder and changes no primary class.
CREDENTIALS_REPORTING_ONLY = "credentials-reporting-only"
CREDENTIALS_TEST_TIME = "credentials-test-time"
CREDENTIALS_UNCLEAR = "credentials-unclear"
# The test step's own privilege: one of three, mutually exclusive, and present
# wherever a scope holds a pipeline file at all. A narrower question than the
# credentials axis above and asked for the same reason, which is why it is a
# determination of its own rather than a fourth value there. The credentials
# axis asks about EVERY privileged step in a scope, so one unrecognised step
# anywhere holds the whole scope unclear; this asks only whether the step that
# invokes the test suite consumes a credential, which is what a contributor
# wanting a pre-flight signal needs to know. Off the ladder and changing no
# primary class, like the asides above.
TEST_STEP_UNPRIVILEGED = "test-step-unprivileged"
TEST_STEP_PRIVILEGED = "test-step-privileged"
TEST_STEP_UNIDENTIFIED = "test-step-unidentified"

PRECEDENCE = [ACTS_ON_FORGE, WRITES_OUTWARD, READ_CREDENTIAL, SPECIAL_ENV,
              SELF_CONTAINED, NO_PULL_REQUEST_TRIGGER, NO_PIPELINE]
ASIDE = [THIN_WRAPPER, PULL_REQUEST_TARGET, USES_FORGE_TOKEN,
         ASSUMES_TOOLCHAIN, CREDENTIALS_REPORTING_ONLY, CREDENTIALS_TEST_TIME,
         CREDENTIALS_UNCLEAR, TEST_STEP_UNPRIVILEGED, TEST_STEP_PRIVILEGED,
         TEST_STEP_UNIDENTIFIED]

# ---------------------------------------------------------------- credentials

# A secret referenced by name, in either Actions spelling, plus `secrets:
# inherit` on a reusable-workflow call, which passes every secret the caller
# holds and so cannot be read as anything but a secret reference.
SECRET_NAMED = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)")
SECRET_INDEXED = re.compile(
    r"""secrets\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]""")
SECRETS_INHERIT = re.compile(r"^[ \t]*secrets:[ \t]*inherit[ \t]*$", re.M)
# A credential referenced as an ordinary shell variable, where the *name* is
# the only signal available. GitLab is why this exists: it has no `secrets.`
# namespace, so a masked variable (the forge's own `CI_JOB_TOKEN` included)
# can be recognised by nothing but its name, where an Actions workflow names
# `secrets.GITHUB_TOKEN` explicitly. The scan itself is not asymmetric: it runs
# over both grammars, so an Actions workflow's `$API_KEY` raises `secret-ref`
# too and carries the same limitation. The name is a guess about the
# variable's purpose, and NOT_CREDENTIAL is where that guess is corrected.
DOLLAR_VAR = re.compile(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?")
CREDENTIALISH = re.compile(
    r"(TOKEN|PASSWORD|PASSWD|SECRET|APIKEY|API_KEY|_KEY|KEYFILE|"
    r"CREDENTIAL|CREDENTIALS|_PAT|NETRC|_AUTH)$")
# Names the suffix rule above matches that are not credentials. `_KEY` splits
# between secrets (`API_KEY`, `SSH_KEY`, `GPG_KEY`, `DEPLOY_KEY`) and ordinary
# data (a cache key, a sort key, an idempotency key), and no sharpening of the
# pattern can separate them, because both populations are spelled the same way.
# So the suffix stays a heuristic with an exception list, and the list is the
# honest place to carry that: exact names, each one checkable and extensible by
# a reader, rather than a regex whose judgement is unreadable.
#
# `CACHE_KEY` is the entry that earns the whole mechanism: it is among the
# commonest variable names in Actions, since a cache key is routinely computed
# into one, and matching it moves repositories out of `self-contained` and into
# `read-credential`, which is the figure this tool exists to produce.
#
# EXACT NAMES ONLY, which is the remaining limitation: a prefixed spelling
# (`NPM_CACHE_KEY`) still over-claims until it is added here, and an inline
# test password still reads as a credential.
#
# Only the name scan consults this. A `secrets.CACHE_KEY` reference is
# untouched: there the workflow has declared the thing a secret, and the name
# is no longer being guessed at.
NOT_CREDENTIAL = {
    # Cache keys: computed, then matched against a restore key.
    "CACHE_KEY", "RESTORE_KEY", "BASE_KEY", "FALLBACK_KEY",
    # Database and data-structure keys.
    "PRIMARY_KEY", "FOREIGN_KEY", "SORT_KEY", "PARTITION_KEY", "RANGE_KEY",
    "ROW_KEY", "SHARD_KEY", "GROUP_KEY", "INDEX_KEY", "OBJECT_KEY",
    # Request identity: deduplication and tracing, not authentication.
    "IDEMPOTENCY_KEY", "DEDUPE_KEY", "LOCK_KEY", "CORRELATION_KEY",
    # A name looked up in a message catalogue or a config map.
    "TRANSLATION_KEY", "LOCALE_KEY", "CONFIG_KEY", "MAP_KEY",
}
# Minted by whichever forge runs the job, so nobody has to supply them.
FORGE_TOKENS = {"GITHUB_TOKEN", "GITEA_TOKEN", "FORGEJO_TOKEN", "CI_JOB_TOKEN"}

# ---------------------------------------------------------------- the acts

OUTWARD = [
    ("container-push", re.compile(
        r"\b(?:docker|podman|nerdctl)\s+(?:image\s+)?push\b"
        r"|\bskopeo\s+copy\b|\bbuildah\s+push\b"
        r"|\bbuildah\s+bud\b[^\n]*--push", re.I)),
    # docker/build-push-action defaults to push: false and is extremely common
    # as a build-only pull-request check, so the action alone is not the
    # signal. pushes_image() carries the reading.
    ("build-push-action", re.compile(r"docker/build-push-action", re.I)),
    ("package-publish", re.compile(
        r"\b(?:npm|yarn|pnpm|bun)\s+publish\b|\btwine\s+upload\b"
        r"|\bcargo\s+publish\b|\bgem\s+push\b|\bhelm\s+push\b"
        r"|\bpoetry\s+publish\b|\bflit\s+publish\b|\bnuget\s+push\b"
        r"|\bdotnet\s+nuget\s+push\b|\bmvn\b[^\n]*\bdeploy\b"
        r"|\b\.?/?gradlew?\b[^\n]*\bpublish\b|\bsbt\b[^\n]*\bpublish\b"
        r"|\bmix\s+hex\.publish\b|\bgoreleaser\s+release\b", re.I)),
    ("publish-action", re.compile(
        r"pypa/gh-action-pypi-publish|JS-DevTools/npm-publish"
        r"|redhat-actions/push-to-registry", re.I)),
    ("pages-deploy", re.compile(
        r"peaceiris/actions-gh-pages|JamesIves/github-pages-deploy-action"
        r"|actions/deploy-pages|crazy-max/ghaction-github-pages", re.I)),
    ("deploy-cli", re.compile(
        r"\baws\s+s3\s+(?:cp|sync|mv|rm)\b"
        r"|\baws\s+(?:lambda|ecs|ecr|cloudfront|elasticbeanstalk|deploy)\b"
        r"|\baz\s+(?:webapp|acr|functionapp|storage)\b"
        r"|\bgcloud\s+(?:app|run|functions|builds|container|storage)\b"
        r"|\bkubectl\s+(?:apply|create|delete|patch|replace|rollout|set)\b"
        r"|\bhelm\s+(?:upgrade|install)\b|\bterraform\s+apply\b"
        r"|\bterragrunt\s+apply\b|\bpulumi\s+up\b|\bansible-playbook\b"
        r"|\b(?:flyctl|fly)\s+deploy\b|\bvercel\b[^\n]*--prod"
        r"|\bnetlify\s+deploy\b|\bwrangler\s+(?:deploy|publish)\b"
        r"|\bserverless\s+deploy\b|\bsls\s+deploy\b|\bcf\s+push\b"
        r"|\beb\s+deploy\b|\bdoctl\s+apps\b|\bheroku\s+(?:deploy|container)\b"
        r"|\brclone\s+(?:copy|sync)\b", re.I)),
    ("deploy-action", re.compile(
        r"appleboy/ssh-action|appleboy/scp-action|easingthemes/ssh-deploy"
        r"|SamKirkland/FTP-Deploy-Action|burnett01/rsync-deployments"
        r"|superfly/flyctl-actions|aws-actions/amazon-ecs-deploy"
        r"|azure/webapps-deploy|google-github-actions/deploy"
        r"|cloudflare/wrangler-action|nwtgck/actions-netlify"
        r"|amondnet/vercel-action|akhileshns/heroku-deploy"
        r"|azure/functions-action|wzieba/AppCenter-Github-Action"
        r"|getsentry/action-release", re.I)),
    ("remote-copy", re.compile(
        r"\brsync\b|\bscp\s+\S|\bsftp\s+\S|\blftp\b"
        r"|\bssh\s+(?:-\S+\s+)*[\w.-]+@", re.I)),
    # A deployment environment in either forge's spelling. The key only exists
    # to name something being deployed to.
    ("deployment-environment", re.compile(r"^[ \t]*environment:[ \t]*\S", re.M)),
    # Writing a commit back out of the pipeline. Not the forge API, so it is an
    # outward write rather than acts-on-forge.
    ("git-push", re.compile(r"\bgit\s+push\b", re.I)),
    # The same act wrapped in an action, where no `git push` appears in any
    # `run:` body to catch it.
    ("commit-push-action", re.compile(
        r"ad-m/github-push-action|stefanzweifel/git-auto-commit-action"
        r"|EndBug/add-and-commit|cpina/github-action-push-to-another-repository",
        re.I)),
    # Two permission grants that are outward writes rather than forge-API
    # writes, which is why they sit here and not with `permissions-write`.
    # `packages: write` is the grant to publish to a package registry.
    # `id-token: write` mints an OIDC token, the keyless path to a cloud
    # account, a registry or a signature. For that case the permission is
    # the only evidence there is, precisely because the token replaces the
    # credential a `secrets.` reference or a credential-shaped variable name
    # would otherwise expose. A keyless publish carries no secret to detect.
    ("packages-write", re.compile(r"^[ \t]*packages:[ \t]*['\"]?write\b", re.M)),
    ("id-token-write", re.compile(r"^[ \t]*id-token:[ \t]*['\"]?write\b", re.M)),
]

FORGE = [
    # actions/github-script runs JavaScript with an authenticated client in
    # scope, so the action alone does not say the forge API is reached: plenty
    # of steps use it only for `core.info` / `core.exportVariable`, where the
    # client is never touched. The script body is the signal.
    ("github-script", re.compile(r"actions/github-script", re.I)),
    ("gh-cli", re.compile(
        r"\bgh\s+(?:issue|pr|release|api|label|workflow|secret|variable)\b")),
    ("glab-cli", re.compile(r"\bglab\s+(?:issue|mr|release|api)\b")),
    ("forge-api-url", re.compile(
        r"api\.github\.com|github\.api_url|/api/v1/repos|CI_API_V4_URL", re.I)),
    ("release-action", re.compile(
        r"softprops/action-gh-release|actions/create-release"
        r"|ncipollo/release-action|svenstaro/upload-release-action"
        r"|release-drafter/release-drafter|goreleaser/goreleaser-action", re.I)),
    ("issue-pr-action", re.compile(
        r"actions/labeler|actions/stale|peter-evans/create-pull-request"
        r"|peter-evans/create-or-update-comment|peter-evans/close-issue"
        r"|thollander/actions-comment-pull-request"
        r"|marocchino/sticky-pull-request-comment"
        r"|actions-ecosystem/action-add-labels|dessant/lock-threads"
        r"|mshick/add-pr-comment|crazy-max/ghaction-github-labeler"
        r"|MishaKav/pytest-coverage-comment"
        r"|py-cov-action/python-coverage-comment-action", re.I)),
    # Minting a forge token from a GitHub App's id and private key. The token
    # it hands the rest of the job carries the App's own write scopes, so this
    # is forge-side privilege however the later steps use it. Unlike
    # `secrets.GITHUB_TOKEN` it is not minted by whoever runs the job: the App
    # credentials are a secret a contributor's instance would have to be given.
    ("forge-app-token", re.compile(
        r"actions/create-github-app-token|tibdex/github-app-token", re.I)),
    # `contents: write` is deliberately absent: it is git write rather than a
    # forge-API write, it is granted by nearly every release workflow, and
    # those are already caught by their publish or release signal. `packages:`
    # and `id-token:` are absent on the same distinction and live in OUTWARD
    # instead: they grant a write to a registry or a cloud account, not to
    # this forge's API.
    ("permissions-write", re.compile(
        r"^[ \t]*(?:issues|pull-requests|discussions|deployments):"
        r"[ \t]*['\"]?write\b|^[ \t]*permissions:[ \t]*write-all\b", re.M)),
]
# GitLab only: `release:` is a job keyword that creates a release through the
# API. In an Actions workflow the same word is a trigger name under `on:`, so
# this cannot be applied to every file.
GITLAB_FORGE = [
    ("gitlab-release", re.compile(r"^[ \t]*release:[ \t]*$|"
                                  r"^[ \t]*release:[ \t]*\S", re.M)),
]

ENVIRONMENT = [
    # A container job on Actions is a different runner shape from the default
    # one. GitLab's `image:` is NOT this: there, a container is the normal mode.
    ("container-job", re.compile(r"^[ \t]*container:[ \t]*(?:\S|$)", re.M)),
    ("virt-or-gpu", re.compile(
        r"nvidia|cuda|--gpus|/dev/kvm|\bkvm\b|nested[-_ ]?virt"
        r"|qemu-system|reactivecircus/android-emulator-runner|\bgpu\b", re.I)),
]

RUNS_ON = re.compile(r"^[ \t]*runs-on:[ \t]*(.+)$", re.M)
# Matrix entries and `strategy.matrix.os` lists, whichever key they hang under.
OS_LIST_ITEM = re.compile(
    r"^[ \t]*-[ \t]*['\"]?((?:ubuntu|windows|macos|mac-os|macOS|self-hosted|"
    r"debian|fedora|alpine)[\w.\-]*)['\"]?[ \t]*$", re.M | re.I)
NON_LINUX = re.compile(r"windows|macos|mac-os|darwin|self-hosted", re.I)
NON_X86 = re.compile(r"\barm\b|arm64|aarch64|\bppc64|\bs390x", re.I)
# GitLab runner tags that cannot be a stock Linux x86 shared runner. A bare
# `tags: [docker]` is the normal case and is not one.
GITLAB_SPECIAL_TAGS = re.compile(
    r"windows|macos|saas-macos|\barm\b|arm64|aarch64|shell|gpu", re.I)
GITLAB_TAGS_BLOCK = re.compile(r"^[ \t]*tags:[ \t]*(.*)$", re.M)

# The `push:` input of docker/build-push-action, with whatever value it was
# given. See pushes_image() for what the value has to be.
PUSH_INPUT = re.compile(r"^[ \t]*push:[ \t]*(\S.*?)[ \t]*$", re.M)
# Values that are not a push. A literal `false` is the build-only case. The
# rest are the shapes the `on:` trigger of the same name takes when it is
# written on one line (a branch-filter collection, or an explicit empty
# value), and a trigger is not an action input.
NOT_A_PUSH = re.compile(r"""^(?:['"]?false['"]?|null|~|[\[{].*)$""", re.I)

# An actions/github-script body reaching the forge API: the authenticated
# client's three entry points.
GITHUB_SCRIPT_API = re.compile(r"\bgithub\.(?:rest|graphql|request)\b")

# What a pipeline assumes is already installed on the runner. Not a privilege
# class; see "`self-contained` is not `runs on a bare runner`" in classify.py.
#
# The `actions/setup-*` family is matched as a family rather than enumerated,
# and the tool's own name becomes the signal (`toolchain-node`,
# `toolchain-python`, `toolchain-go`), so the evidence says *what* a runner
# image would have to carry without a table of action names to keep current.
SETUP_ACTION = re.compile(r"\bactions/setup-([A-Za-z0-9.+]+)", re.I)
# A job naming its own image states its environment outright: Actions'
# `container:` (and the `image:` key inside it) and GitLab's `image:`, which
# mean the same thing for this question even though only the Actions one is an
# unusual *runner shape* and so only it raises `special-env`. An interpolated
# name (`image: ${{ matrix.image }}`) does not match and is a miss.
JOB_IMAGE = re.compile(
    r"^[ \t]*(?:container|image):[ \t]*['\"]?([A-Za-z0-9][\w./:@-]*)", re.M)
TOOLCHAIN_PREFIX = "toolchain-"

# A run step is a "single invocation" only if it is one command with no shell
# plumbing. These are what make it a wrapper rather than a pipeline: a target,
# a script file, or a task runner's named task.
THIN_FORMS = (
    re.compile(r"^(?:make|just|task|tox|nox|rake|invoke|mage)"
               r"(?:\s+[\w:.,=/\-]+)*$"),
    re.compile(r"^(?:\./|\.\\)[\w./\\\-]+(?:\s+[\w:.,=/\-]+)*$"),
    re.compile(r"^(?:bash|sh|zsh|python3?|pwsh|powershell|perl|ruby|node)"
               r"\s+[\w./\\\-]+\.(?:sh|bash|py|ps1|bat|cmd|rb|pl|js|mjs)"
               r"(?:\s+[\w:.,=/\-]+)*$"),
    re.compile(r"^(?:npm|yarn|pnpm|bun)\s+run\s+[\w:.\-]+(?:\s+[\w:.,=/\-]+)*$"),
)
SHELL_PLUMBING = re.compile(r"&&|\|\||[;|<>`]|\$\(")


def is_thin(command):
    """Whether one step is a single invocation of a script or make target.

    A statement about shape, not privilege: every run step being one
    invocation means a contributor can reproduce the pipeline by hand,
    whatever else it needs granted.
    """
    lines = [l.strip() for l in command.splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    if len(lines) != 1:
        return False
    cmd = lines[0]
    if SHELL_PLUMBING.search(cmd):
        return False
    return any(p.match(cmd) for p in THIN_FORMS)


def pushes_image(text):
    """Whether a `push:` input says the built image is pushed.

    Present and not literally `false`, which is the semantics of the input
    itself: `push: ${{ github.event_name != 'pull_request' }}` is the form
    GitHub's own starter workflow uses, and a conditional push is a push. The
    build-only case the action defaults to is the input being absent or
    `false`, and that is the only case this stays silent for.
    """
    return any(not NOT_A_PUSH.match(m.group(1))
               for m in PUSH_INPUT.finditer(text))


def github_script_writes(text):
    """Whether an actions/github-script step reaches the forge API.

    The body referencing `github.rest`, `github.graphql` or `github.request`
    is the evidence. Where no body can be isolated at all (the step takes its
    script from somewhere this cannot see), the answer is yes: the signal
    decides the top class, so the over-claim keeps a real forge write visible
    while the under-claim would hide one, and hiding it is worse.
    """
    bodies = actions_script_bodies(text)
    if not bodies:
        return True
    return any(GITHUB_SCRIPT_API.search(b) for b in bodies)


# --------------------------------------- reporting versus test time

# Privileged steps that exist to record a result rather than to produce one,
# matched by exact name, the strongest evidence available here. The table is
# extensible without re-auditing anything else: a tool it has never heard of
# reads as an unrecognised privileged step, which costs a `reporting-only`
# reading rather than producing a wrong one.
REPORTING = [
    ("reporting-coverage", re.compile(
        r"codecov/codecov-action|codecov/test-results-action"
        r"|coverallsapp/github-action|paambaati/codeclimate-action"
        r"|5monkeys/cobertura-action|irongut/CodeCoverageSummary"
        r"|romeovs/lcov-reporter-action|codecov\.io"
        r"|\bcodecov(?:-cli)?\b|\bcoveralls\b|\bcc-test-reporter\b", re.I)),
    ("reporting-code-quality", re.compile(
        r"SonarSource/[\w.-]+|\bsonar-scanner\b|\bsonar:sonar\b"
        r"|\bsonarqube\b|\bsonarcloud\b", re.I)),
    ("reporting-test-results", re.compile(
        r"dorny/test-reporter|EnricoMi/publish-unit-test-result-action"
        r"|mikepenz/action-junit-report|test-summary/action"
        r"|phoenix-actions/test-reporting", re.I)),
    ("reporting-comment", re.compile(
        r"marocchino/sticky-pull-request-comment"
        r"|peter-evans/create-or-update-comment|peter-evans/find-comment"
        r"|thollander/actions-comment-pull-request|mshick/add-pr-comment"
        r"|reviewdog/action-[\w.-]+"
        # The coverage comments, which are the forge-side twin of a coverage
        # upload: the same number, posted on the pull request instead of sent
        # to a service. They name the act in the action's own name, so the
        # exact-name standard the rest of this table holds to is met.
        r"|MishaKav/pytest-coverage-comment"
        r"|py-cov-action/python-coverage-comment-action", re.I)),
    ("reporting-code-scanning", re.compile(
        r"github/codeql-action/upload-sarif", re.I)),
    ("reporting-notify", re.compile(
        r"slackapi/slack-github-action|8398a7/action-slack"
        r"|rtCamp/action-slack-notify|act10ns/slack"
        r"|skitionek/notify-microsoft-teams|jdcargile/ms-teams-notification"
        r"|s3krit/matrix-message-action|fadenb/matrix-chat-message"
        r"|Ilshidur/action-discord|sarisia/actions-status-discord"
        r"|appleboy/telegram-action|hooks\.slack\.com"
        r"|discord\.com/api/webhooks|webhook\.office\.com"
        r"|/_matrix/client/", re.I)),
]
REPORTING_CONDITIONAL = "reporting-conditional"
# A privileged step written to run whatever the tests did, which is evidence
# about its purpose even where its tool is in no table: a step the tests depend
# on is not written this way.
RUNS_REGARDLESS = re.compile(
    r"^[ \t]*(?:-[ \t]+)?if:[ \t]*.*?\b(?:always|failure)[ \t]*\([ \t]*\)",
    re.M)
CONTINUE_ON_ERROR = re.compile(
    r"^[ \t]*(?:-[ \t]+)?continue-on-error:[ \t]*['\"]?true\b", re.M)
# The one shape that reads the condition above backwards. A step written
# `if: always()` that tears something down is a cleanup, not a record: the
# condition is there so the resources go away even when the tests failed, and
# skipping it leaks them. So a teardown is never read as reporting on the
# strength of how it is written, only on a name in REPORTING, which no
# teardown carries.
TEARDOWN = re.compile(
    r"\b(?:terraform|terragrunt|pulumi|vagrant)\s+destroy\b"
    r"|\bkubectl\s+delete\b|\bhelm\s+(?:uninstall|delete)\b"
    r"|\baws\s+cloudformation\s+delete\b|\baz\s+group\s+delete\b"
    r"|\bgcloud\s+\S+\s+delete\b|\bdoctl\s+\S+\s+delete\b", re.I)

# An actions/github-script body that only comments or sets a status. The same
# reading as github_script_writes() and the opposite default: there the
# over-claim keeps a real forge write visible, here an unreadable body must not
# buy a reporting-only reading.
GITHUB_SCRIPT_CALL = re.compile(r"\bgithub\.(?:rest[\w.]*|graphql|request)")
GITHUB_SCRIPT_REPORT = re.compile(
    r"github\.rest\.(?:issues\.(?:createComment|updateComment|listComments)"
    r"|pulls\.(?:listReviewComments|createReviewComment)"
    r"|checks\.(?:create|update)|repos\.createCommitStatus)")

# Credentials dependency resolution needs, as (signal, credential, command).
# Both halves have to be in the file: the credential's name says which registry
# it is for, and the command says that registry is being read from. This is the
# inverse signal, and it is decisive: a pipeline missing one of these has
# nothing to compile, so the privilege is not droppable at any price.
JVM_BUILD = re.compile(
    r"\bmvn\b[^\n]*\b(?:test|verify|package|install|compile|site)\b"
    r"|\b\.?/?gradlew?\b[^\n]*\b(?:test|check|build|assemble|jar|classes)\b")
TEST_TIME = [
    ("dep-credential-npm",
     re.compile(r"\bNODE_AUTH_TOKEN\b|\bNPM_TOKEN\b|\bNPM_AUTH_TOKEN\b"
                r"|_authToken"),
     re.compile(r"\b(?:npm|yarn|pnpm|bun)\s+(?:ci|install|i|add)\b")),
    ("dep-credential-jvm",
     re.compile(r"s4u/maven-settings-action|settings\.xml"
                r"|\bMAVEN_[A-Z0-9_]*(?:USERNAME|USER|PASSWORD|TOKEN|SECRET)\b"
                r"|\bMVN_[A-Z0-9_]*(?:USERNAME|USER|PASSWORD|TOKEN)\b"
                r"|\bORG_GRADLE_PROJECT_\w*"
                r"(?:[Uu]ser|[Pp]assword|[Tt]oken|[Kk]ey)"
                r"|\bGRADLE_[A-Z0-9_]*(?:USERNAME|USER|PASSWORD|TOKEN)\b"
                r"|\b(?:ARTIFACTORY|NEXUS|JFROG)_[A-Z0-9_]*"
                r"(?:USERNAME|USER|PASSWORD|TOKEN|SECRET|API_KEY|APIKEY)\b"),
     JVM_BUILD),
    ("dep-credential-pip",
     re.compile(r"(?:--(?:extra-)?index-url[= ]|PIP_(?:EXTRA_)?INDEX_URL)"
                r"[^\n]*(?:@|\$\{|\$[A-Z])"),
     re.compile(r"\bpip3?\s+install\b|\bpoetry\s+(?:install|lock)\b"
                r"|\buv\s+(?:sync|pip)\b|\bpip-sync\b")),
    ("dep-credential-nuget",
     re.compile(r"\bNUGET_AUTH_TOKEN\b"
                r"|\bNUGET_[A-Z0-9_]*(?:PASSWORD|TOKEN)\b"),
     re.compile(r"\bdotnet\s+(?:restore|build|test)\b|\bnuget\s+restore\b")),
    ("dep-credential-composer",
     re.compile(r"\bCOMPOSER_AUTH\b"
                r"|\bCOMPOSER_[A-Z0-9_]*(?:PASSWORD|TOKEN)\b"),
     re.compile(r"\bcomposer\s+(?:install|update|require)\b")),
    ("dep-credential-bundler",
     re.compile(r"\bBUNDLE_[A-Z0-9_]*(?:PASSWORD|TOKEN|CREDENTIALS)\b"
                r"|\bBUNDLE_GEMS__\w+"),
     re.compile(r"\bbundle\s+install\b")),
    ("dep-credential-cargo",
     re.compile(r"\bCARGO_REGISTRIES_[A-Z0-9_]*TOKEN\b"),
     re.compile(r"\bcargo\s+(?:build|test|fetch|check)\b")),
    # The credential sits in a git URL rewrite, so every later fetch of a
    # private dependency carries it. The commonest private-Go shape, and used
    # for private npm and Composer dependencies too.
    ("dep-credential-git-rewrite",
     re.compile(r"\binsteadOf\b"),
     re.compile(r"\bgo\s+(?:mod|build|test|get)\b|\bgit\s+config\b")),
]
# A private registry explains a *pull* only while nothing here is pushed to
# one. A publish explains the same credential better, and a publish is not a
# step a contributor drops and still has a release.
PUBLISHES = {"package-publish", "publish-action", "container-push",
             "build-push-action", "packages-write"}
# A `docker login` before a `docker build` authenticates the pull of a private
# base image. After the build, or anywhere near a push, it is the publish's
# credential instead, so the order and the absence of a push are both
# required.
DOCKER_LOGIN = re.compile(
    r"\bdocker\s+login\b|\b(?:podman|buildah)\s+login\b|docker/login-action",
    re.I)
DOCKER_BUILD = re.compile(
    r"\b(?:docker|podman|nerdctl)\s+(?:image\s+)?build\b|\bbuildah\s+bud\b"
    r"|docker/build-push-action", re.I)
REGISTRY_PULL = "dep-credential-registry-pull"
# Cloud authentication, by exact action name plus the CLI spellings. Real
# authentication against somebody's cloud account, and the one thing it
# certainly is not is a record of what the run found, so the axis has an
# answer for it and should give it rather than shrug.
#
# It answers test-time where a test runs after the authentication: those tests
# cannot reach the cloud without it. Two gates, because a cloud credential is
# far more often a deploy's than a test's. Nothing fires where the file spends
# the credential outward; then it is the push's or the deploy's, and that act
# is already keeping the scope out of `reporting-only` on its own evidence. And
# nothing fires where no test follows the authentication, which is what catches
# the deploy whose act is hidden in a `./scripts/deploy.sh` wrapper.
CLOUD_AUTH = re.compile(
    r"aws-actions/configure-aws-credentials|aws-actions/amazon-ecr-login"
    r"|azure/login|google-github-actions/auth"
    r"|\baws\s+configure\s+set\b|\baz\s+login\b"
    r"|\bgcloud\s+auth\s+(?:login|activate-service-account)\b", re.I)
CLOUD_CREDENTIAL = "cloud-credential"
TEST_TIME_SIGNALS = ({n for n, _, _ in TEST_TIME}
                     | {REGISTRY_PULL, CLOUD_CREDENTIAL})
REPORTING_SIGNALS = {n for n, _ in REPORTING} | {REPORTING_CONDITIONAL}
# Acts that are never a reporting step whatever else the step also does. A step
# that publishes, deploys or pushes a commit produces something outside the run
# rather than recording what happened in it, so a reporting name sitting in the
# same step does not buy it a reporting reading.
NEVER_REPORTING = PUBLISHES | {"deploy-cli", "deploy-action", "pages-deploy",
                               "remote-copy", "git-push", "commit-push-action"}
# Acts that explain a cloud credential better than test time does: the
# credential is what the push, the deploy or the publish needs, and that is not
# a step a contributor skips and still has a result.
CREDENTIAL_SPENDERS = PUBLISHES | {"deploy-cli", "deploy-action",
                                   "pages-deploy", "remote-copy"}
# Steps that consume no privilege, matched by exact name, the counterpart of
# REPORTING and relied on for the opposite purpose. Build plumbing: a checkout,
# a toolchain setup, a cache, an artifact transfer, a container-build helper.
# Without this list a step from this family reads as an unrecognised privileged
# step wherever anything in it trips a name-shaped credential guess, and that
# over-claim is paid for by a `reporting-only` reading the scope deserved.
#
# `actions/upload-artifact` is on the list and is the entry a reviewer will
# challenge first, because it is how a result leaves a run. The axis asks one
# question only (does this step consume a privilege somebody has to grant),
# and an artifact upload consumes none: it writes to the run's own storage with
# no credential and no secret. Whether an artifact is how a result gets
# published is a different question and not this one.
#
# Membership never overrides a credential handed to the step. neutral_step()
# requires the step to reference none of its own, so an `actions/checkout`
# given a personal access token, or a `hashicorp/setup-terraform` given a
# Terraform Cloud token, is judged on that credential like any other step.
NEUTRAL_ACTION = re.compile(
    r"\bactions/(?:checkout|setup-[\w.+-]+|cache(?:/(?:restore|save))?"
    r"|upload-artifact|download-artifact|upload-pages-artifact)\b"
    # The container-build helpers that set a builder up without building: the
    # build and the push are their own signals and are caught there.
    r"|\bdocker/(?:metadata-action|setup-buildx-action|setup-qemu-action)\b"
    # Toolchain setups outside the actions/ namespace, which is most of them
    # once a language brings its own. The r-lib family installs R, its
    # dependencies, pandoc and TinyTeX and runs the package check.
    r"|\br-lib/actions/[\w.-]+"
    r"|\bastral-sh/setup-uv\b|\bpnpm/action-setup\b|\bdtolnay/rust-toolchain\b"
    r"|\bmamba-org/setup-micromamba\b|\bquarto-dev/quarto-actions/setup\b"
    r"|\bcachix/install-nix-action\b|\blukka/get-cmake\b"
    r"|\bgradle/(?:actions/setup-gradle|gradle-build-action)\b"
    # Installing a cloud CLI is not authenticating to a cloud: `azure/login`
    # and `google-github-actions/auth` are, and they are in CLOUD_AUTH. The
    # `kubectl apply` or `helm upgrade` these put on the PATH is its own signal.
    r"|\bazure/setup-(?:helm|kubectl)\b|\bhashicorp/setup-terraform\b"
    # Reading the event to decide what to run. Neither reaches the forge API.
    r"|\bdorny/paths-filter\b|\bnrwl/nx-set-shas\b", re.I)
# What keeps a scope out of `reporting-only`: a privileged step not recognised
# as reporting (because nothing matched it, or because what it does is not a
# record of the run however the step is named); a privilege no step could be
# attributed; and a recognised reporting step that runs before any test, which
# is the one thing step order is allowed to decide. Any of the three is enough:
# that is the asymmetry.
UNRECOGNISED_PRIVILEGED_STEP = "unrecognised-privileged-step"
UNATTRIBUTED_PRIVILEGE = "unattributed-privilege"
REPORTING_BEFORE_TESTS = "reporting-step-before-tests"
UNCLEAR_SIGNALS = {UNRECOGNISED_PRIVILEGED_STEP, UNATTRIBUTED_PRIVILEGE,
                   REPORTING_BEFORE_TESTS}
# Not an act but a grant. A permissions block or a named deployment environment
# grants nothing by itself and is only ever exercised by a step, so it is
# attributed to the steps that use it rather than counted as a privilege of its
# own; otherwise the `permissions: pull-requests: write` that a sticky comment
# needs would be an unattributable privilege and no comment step could ever
# read as reporting.
GRANT_SIGNALS = {"packages-write", "id-token-write", "permissions-write",
                 "deployment-environment"}
# The grants that grant nothing on their own, so one nothing consumes is a line
# that does nothing rather than a privilege a contributor needs. A forge
# `permissions:` block is copied between workflows constantly (a repository
# carrying `pull-requests: write` for a comment step somebody later deleted is
# the ordinary case, not the edge), and it is the only grant here that reads
# that way.
#
# The others are the opposite case by design, and they stay privileges wherever
# no step can be attributed them: for a keyless publish `packages: write` or
# `id-token: write` is the ONLY evidence the write exists, and a named
# `environment:` exists to name something being deployed to.
BOILERPLATE_GRANTS = {"permissions-write"}
# A boilerplate grant no visible step could be attributed to. Recorded as
# evidence and deliberately NOT in UNCLEAR_SIGNALS: letting it decide the
# verdict alone held a large share of a corpus out of the derived figure on the
# strength of a line nothing exercises.
#
# The failure mode this accepts, stated because it is real and not small: a
# grant whose consumer the reader simply failed to see now reads as unused.
# Where a step cannot be isolated (a shape the structural reading does not
# handle, a `make deploy` target, a command assembled from variables), the
# grant looks unexercised when the step exercising it is merely invisible, and
# the scope then reads reporting-only or carries no verdict at all instead of
# unclear. That is the flattering direction, which is why the signal is kept
# greppable rather than dropped.
#
# Two shapes of that failure are big enough to answer directly, and both are
# answered by refusing the reading rather than by guessing at the consumer:
# OPAQUE_STEP below, where the steps are not in this file at all, and a file
# that references the forge's own token. A `permissions:` block is what scopes
# that token, so a file naming it has a plausible consumer for its grant in
# every step the token is passed to, including the ones no table here
# recognises, which is how the commonest false reading arose: a step that
# backports or labels using `secrets.GITHUB_TOKEN` carries no secret-ref, so it
# is not a privileged unit, so the grant it exercises looked unexercised.
UNUSED_GRANT = "unused-grant"
# A step whose body is in a file this does not fetch: a reusable workflow
# called as a job (`jobs.<id>.uses:` naming a `.yml`), or a composite action in
# a directory of its own. Either way the step list is incomplete, so a grant
# cannot be called unused on the strength of it. A grant passed down to a
# called workflow is the ordinary reason to declare one.
OPAQUE_STEP = re.compile(
    r"^[ \t]*(?:-[ \t]+)?uses:[ \t]*['\"]?(?:\S+\.ya?ml(?:@\S+)?"
    r"|\.[\w./-]+)['\"]?[ \t]*$", re.M)
# Where the tests are. An EXPLICIT LIST OF COMMAND FORMS, which is the whole of
# the mechanism: recognition, never inference. There is no rule here that reads
# an unfamiliar command and decides it looks like a test run, and
# test_step_signals() answers "not identifiable" for one rather than guessing.
#
# Two callers, and the error direction is opposite for each, which is why the
# list is kept to command forms that mean a test run and nothing else:
#
#   - THE ORDER TIEBREAK in privilege_purpose(). There a wider list demotes
#     more reporting readings, which is the conservative direction, so a
#     spurious match costs nothing.
#   - THE TEST-STEP DETERMINATION below. There a spurious match is the
#     FLATTERING direction: a step that is not a test run but holds no
#     credential would read as a test suite that runs unprivileged. So a form
#     that is also an ordinary English word, or a build command that only
#     sometimes runs tests, stays off the list.
#
# The clusters beyond the first-pass list (pytest, tox, the npm family, go,
# cargo, maven, gradle, dotnet, rspec, phpunit, jest, vitest, make, ctest,
# bats) are each a language ecosystem's single conventional test entry point,
# which is what makes them unambiguous: `mix test`, `swift test`,
# `cabal`/`stack test`, `dune runtest`, `deno test`, `flutter`/`dart test`,
# `meson`/`ninja test`, `zig build test`, and the alternative runners for
# ecosystems already here (`py.test`, `gotestsum`, `ginkgo`,
# `cargo nextest`, `cypress run`, `composer test`, `sbt ... test`,
# `R CMD check`). `ant` joins the task-runner family for the same reason the
# others are in it: the target is named on the command line, so `ant ... test`
# says what it runs.
TEST_INVOCATION = re.compile(
    r"\bpytest\b|\btox\b|\bnox\b|\b(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?test\b"
    r"|\bgo\s+test\b|\bcargo\s+test\b|\bdotnet\s+test\b|\bctest\b"
    r"|\bmvn\b[^\n]*\b(?:test|verify)\b"
    r"|\b\.?/?gradlew?\b[^\n]*\b(?:test|check)\b"
    r"|\b(?:make|just|task|rake|invoke|ant)\s+(?:[\w:.=/-]+\s+)*"
    r"(?:test|check)\b"
    r"|\bphpunit\b|\brspec\b|\bjest\b|\bvitest\b|\bmocha\b|\bbats\b"
    r"|\bpython3?\s+-m\s+(?:pytest|unittest)\b|\bbehave\b"
    r"|\bplaywright\s+test\b|\bRscript\b[^\n]*\btest"
    r"|\bpy\.test\b|\bgotestsum\b|\bginkgo\b|\bcargo\s+nextest\b"
    r"|\bcomposer\s+(?:run\s+)?test\b|\bmix\s+test\b|\bsbt\b[^\n]*\btest\b"
    r"|\bdune\s+(?:test|runtest)\b|\bswift\s+test\b|\bdeno\s+test\b"
    r"|\b(?:flutter|dart)\s+test\b|\b(?:meson|ninja)\s+test\b"
    r"|\b(?:cabal|stack)\s+test\b|\bcypress\s+run\b|\bzig\s+build\s+test\b"
    r"|\bR\s+CMD\s+check\b", re.I)
# The largest cluster of credentials a corpus of this shape leaves unexplained:
# a build-only Maven or Gradle workflow holding a secret, which is very likely
# a private registry whose name gives nothing away. Recorded as evidence on the
# unclear cases rather than resolved into a verdict: the reading would be a
# guess, and the point of the signal is that the evidence cache makes the
# cluster greppable so somebody can settle it by reading the files instead of
# re-fetching them.
JVM_BUILD_SECRET = "jvm-build-secret"

# ------------------------------------------- the test step's own privilege
#
# The evidence behind the three values at the top of this module, one signal
# per reason, so the residual is greppable out of the cache by cause rather
# than only countable. A later differential-execution run has to cover exactly
# the units these name.
#
# A test step runs unprivileged on the strength of one signal only, and it is
# a positive finding about a step that was identified:
TEST_STEP_CLEAN = "test-step-clean"
# Everything else is privileged. These three are findings: something was seen
# reaching the step.
TEST_STEP_CREDENTIAL = "test-step-credential"
TEST_STEP_INHERITED_CREDENTIAL = "test-step-inherited-credential"
TEST_STEP_PRIVILEGED_ACT = "test-step-privileged-act"
# And these two are refusals: the step is there and whether a credential
# reaches it cannot be settled, because the enclosing scope could not be cut
# out of the file, or it was cut from a file that is not the whole
# configuration. Privileged, which is the asymmetry the credentials axis
# already enforces and the reason the figure is not flattering by default.
TEST_STEP_SCOPE_UNREADABLE = "test-step-scope-unreadable"
TEST_STEP_SCOPE_INCOMPLETE = "test-step-scope-incomplete"
# Recorded beside the verdict and deciding nothing, which is what keeps the
# forge-token carve-out in one place: a test step reached by the forge's own
# auto-minted token and by nothing else runs unprivileged, because a
# contributor supplies nothing for that token. Folding it into
# TEST_STEP_CREDENTIAL would tell a reader they need a secret they do not;
# leaving it unrecorded would hide the size of the judgement. Same reading as
# the `forge-token` signal, reported separately so it can be re-sliced here
# too.
TEST_STEP_FORGE_TOKEN = "test-step-forge-token"
TEST_STEP_PRIVILEGED_SIGNALS = {
    TEST_STEP_CREDENTIAL, TEST_STEP_INHERITED_CREDENTIAL,
    TEST_STEP_PRIVILEGED_ACT, TEST_STEP_SCOPE_UNREADABLE,
    TEST_STEP_SCOPE_INCOMPLETE}
TEST_STEP_SIGNALS = TEST_STEP_PRIVILEGED_SIGNALS | {TEST_STEP_CLEAN,
                                                    TEST_STEP_FORGE_TOKEN}
# Authentications that consume a credential the file need not name: a registry
# login reading a password off stdin or out of a file, a cloud login whose
# credentials arrive through an action's `with:`. Compound commands are why
# this is here rather than left to the credential scan: `docker login
# --password-stdin < /run/secrets/pw && npm test` hands the test step a
# session nobody can see in a variable name.
STEP_AUTHENTICATES = (DOCKER_LOGIN, CLOUD_AUTH)
# Configuration this file is not the whole of, so a credential could be
# inherited from text that was never fetched. GitLab's `include:` pulls in
# another file's global `variables:`, and `extends:` pulls in another job's.
# Both are ordinary GitLab style rather than an edge, so this refuses the
# unprivileged reading for a large share of any GitLab corpus; the signal says
# which, so the cost of the rule is countable instead of hidden.
GITLAB_INHERITS_ELSEWHERE = re.compile(
    r"^include:|^[ \t]+extends:[ \t]*\S", re.M)

GROUPS = {
    WRITES_OUTWARD: {n for n, _ in OUTWARD},
    ACTS_ON_FORGE: {n for n, _ in FORGE} | {n for n, _ in GITLAB_FORGE},
    SPECIAL_ENV: ({n for n, _ in ENVIRONMENT}
                  | {"runs-on-special", "matrix-os", "gitlab-runner-tags"}),
}
# What the purpose axis judges: the acts and the credential reference. Not the
# runner shape, which nobody grants.
PRIVILEGE_SIGNALS = (GROUPS[ACTS_ON_FORGE] | GROUPS[WRITES_OUTWARD]
                     | {"secret-ref"})


def credential_names(text):
    """Credential-looking variable names one text references.

    Both grammars at once: a declared `secrets.` reference, and an ordinary
    shell variable whose name is the only evidence there is. Shared by
    base_signals(), which turns the names into signals, and neutral_step(),
    which asks only whether the step was handed one, so there is one
    definition of what a credential reference looks like.
    """
    names = set(SECRET_NAMED.findall(text)) | set(SECRET_INDEXED.findall(text))
    for n in DOLLAR_VAR.findall(text):
        if n in NOT_CREDENTIAL:
            continue
        if CREDENTIALISH.search(n) or n in FORGE_TOKENS:
            names.add(n)
    return names


def base_signals(kind, text):
    """The privilege, environment and toolchain signals in one file or step.

    Takes the grammar rather than the path, because privilege_purpose() asks
    the same question of a single step, where there is no path to read it off.
    Comment-stripped text, as every caller passes.
    """
    found = set()

    # Credentials. The variable's *name* decides whether it is the forge's own
    # token (supplied by whatever runs the job) or something a contributor
    # would have to be given.
    for n in credential_names(text):
        found.add("forge-token" if n in FORGE_TOKENS else "secret-ref")
    if SECRETS_INHERIT.search(text):
        found.add("secret-ref")

    for name, pat in OUTWARD:
        if not pat.search(text):
            continue
        if name == "build-push-action" and not pushes_image(text):
            continue      # build-only, which is what the action defaults to
        found.add(name)
    for name, pat in FORGE:
        if not pat.search(text):
            continue
        if name == "github-script" and not github_script_writes(text):
            continue      # the script runs, but never against the forge API
        found.add(name)
    if kind == "gitlab":
        for name, pat in GITLAB_FORGE:
            if pat.search(text):
                found.add(name)
        for m in GITLAB_TAGS_BLOCK.finditer(text):
            tail = text[m.start():m.start() + 400]
            if GITLAB_SPECIAL_TAGS.search(tail):
                found.add("gitlab-runner-tags")
    else:
        for name, pat in ENVIRONMENT:
            if pat.search(text):
                found.add(name)
        families, specials = set(), False
        tokens = []
        for m in RUNS_ON.finditer(text):
            tokens += [t.strip().strip("'\"[]")
                       for t in m.group(1).split(",") if t.strip()]
        tokens += [m.group(1) for m in OS_LIST_ITEM.finditer(text)]
        for t in tokens:
            low = t.lower()
            if NON_LINUX.search(low) or NON_X86.search(low):
                specials = True
            if "windows" in low:
                families.add("windows")
            elif "macos" in low or "mac-os" in low or "darwin" in low:
                families.add("macos")
            elif any(k in low for k in
                     ("ubuntu", "linux", "debian", "fedora", "alpine")):
                families.add("linux")
        if specials:
            found.add("runs-on-special")
        if len(families) > 1:
            found.add("matrix-os")

    # Anchored to the `on:` declaration rather than to the word appearing
    # anywhere: a `pull_request_target` in a `run:` step, a URL or a doc path
    # is not a privileged trigger, and this figure is one of the few exact
    # enough to quote outside.
    if kind != "gitlab":
        triggers = actions_triggers(text)
        if triggers and "pull_request_target" in triggers:
            found.add("pull-request-target")

    # What the runner is assumed to already carry. Deliberately outside GROUPS,
    # so it ranks nothing.
    for tool in SETUP_ACTION.findall(text):
        found.add(TOOLCHAIN_PREFIX + tool.lower())
    if JOB_IMAGE.search(text):
        found.add(TOOLCHAIN_PREFIX + "image")
    return found


def github_script_reports(text):
    """Whether an actions/github-script step only records a result.

    Comments, review comments, check runs and commit statuses are records of
    what the run found; anything else the authenticated client can reach is
    not. A body that cannot be isolated answers no, the inverse of
    github_script_writes(). The asymmetry is why: there an unreadable body
    keeps a possible forge write visible, here it must not buy the step a
    reporting-only reading.
    """
    bodies = actions_script_bodies(text)
    if not bodies:
        return False
    calls = [m.group(0) for b in bodies
             for m in GITHUB_SCRIPT_CALL.finditer(b)]
    return bool(calls) and all(GITHUB_SCRIPT_REPORT.fullmatch(c)
                               for c in calls)


def reporting_signals(unit):
    """What says a privileged step records a result rather than produces one."""
    found = {n for n, pat in REPORTING if pat.search(unit)}
    if "actions/github-script" in unit and github_script_reports(unit):
        found.add("reporting-comment")
    if ((RUNS_REGARDLESS.search(unit) or CONTINUE_ON_ERROR.search(unit))
            and not TEARDOWN.search(unit)):
        found.add(REPORTING_CONDITIONAL)
    return found


def neutral_step(unit):
    """Whether a unit is build plumbing that consumes no privilege.

    A step on the NEUTRAL_ACTION list that was handed no credential of its own.
    Both halves are required, and the second is the one that matters: a neutral
    action *given* a secret through `with:` or `env:` is not neutral, so
    membership can never swallow an explicit credential.
    """
    if not NEUTRAL_ACTION.search(unit):
        return False
    return not (credential_names(unit) or SECRETS_INHERIT.search(unit))


def test_time_signals(text, found):
    """Credentials this pipeline cannot run without.

    Nothing fires where the file publishes: a publish explains a registry
    credential better than resolution does, and it is not a step a contributor
    can drop and still have a release.
    """
    if found & PUBLISHES:
        return set()
    out = {name for name, cred, cmd in TEST_TIME
           if cred.search(text) and cmd.search(text)}
    login, build = DOCKER_LOGIN.search(text), DOCKER_BUILD.search(text)
    if login and build and login.start() < build.start():
        out.add(REGISTRY_PULL)
    # Cloud authentication with a test after it, where nothing in the file
    # spends the credential outward. Both gates are required and CLOUD_AUTH
    # says why. The position test is the same mechanism and the same weakness
    # as the docker-login rule above.
    auth = CLOUD_AUTH.search(text)
    if (auth and not found & CREDENTIAL_SPENDERS
            and TEST_INVOCATION.search(text, auth.end())):
        out.add(CLOUD_CREDENTIAL)
    return out


def privilege_purpose(kind, text, found):
    """What the privilege in one pipeline file is for, as signals.

    Evidence rather than a verdict: several files union into one scope, so the
    verdict is credentials_purpose()'s and the asymmetry lives there. What this
    guarantees is that every privileged step nothing recognised says so, which
    is what makes the asymmetry enforceable at all.
    """
    present = found & PRIVILEGE_SIGNALS
    if not present:
        return set()
    out = test_time_signals(text, found)
    # A dependency-resolution rule explains a credential and nothing else, so
    # the step holding one is not also reported as unrecognised.
    explained = {"secret-ref"} if out else set()
    units, _ = privilege_units(kind, text)
    first_test = next((i for i, u in enumerate(units)
                       if TEST_INVOCATION.search(u)), None)
    accounted, any_privileged_unit = set(), False
    for i, unit in enumerate(units):
        sigs = base_signals(kind, unit) & PRIVILEGE_SIGNALS
        if not sigs:
            continue
        if neutral_step(unit):
            # Build plumbing holding no credential of its own, so whatever
            # matched it is an over-claim rather than a privilege to account
            # for. Counted as accounted so the over-claim does not reappear as
            # an unattributable privilege at the end, and deliberately not as a
            # privileged unit: a step that consumes nothing cannot be what a
            # grant in the frame was granted for.
            accounted |= sigs
            continue
        accounted |= sigs
        any_privileged_unit = True
        if not sigs - explained:
            continue
        # The evidence goes in whether or not it carries the verdict: the
        # signal set is what a reader re-slices the labels from, so a
        # recognised tool stays recorded even where something else overrules it.
        reporting = reporting_signals(unit)
        out |= reporting
        if sigs & NEVER_REPORTING or not reporting:
            out.add(UNRECOGNISED_PRIVILEGED_STEP)
        elif first_test is not None and i < first_test:
            # Order, in the one direction it may move anything: a reporting
            # step that runs before any test in the file has not reported on
            # one, so the reading is demoted rather than taken.
            out.add(REPORTING_BEFORE_TESTS)
    leftover = present - accounted - explained
    # A grant is never an act. Where any privileged step is visible, every
    # grant is attributed to it. Where none is, the two kinds part company: a
    # boilerplate grant is recorded as unused and decides nothing, while a
    # grant that is itself the evidence of a write stays an unattributable
    # privilege.
    if any_privileged_unit:
        leftover -= GRANT_SIGNALS
    elif "forge-token" not in found and not OPAQUE_STEP.search(text):
        if leftover & BOILERPLATE_GRANTS:
            out.add(UNUSED_GRANT)
        leftover -= BOILERPLATE_GRANTS
    if leftover:
        out.add(UNATTRIBUTED_PRIVILEGE)
    if out & UNCLEAR_SIGNALS and "secret-ref" in present \
            and JVM_BUILD.search(text):
        out.add(JVM_BUILD_SECRET)
    return out


def credentials_purpose(signals):
    """One scope's place on the axis, or None where it needs no privilege.

    THE ASYMMETRY IS THIS FUNCTION. `reporting-only` is a claim about every
    privileged step in the scope, so it is reachable only once nothing
    test-time and nothing unrecognised is left anywhere in it; a test-time
    credential is decisive, and a single unrecognised or unattributable
    privilege keeps the scope unclear. Reversing the last two tests would let
    the flattering answer win by default.
    """
    if signals & TEST_TIME_SIGNALS:
        return CREDENTIALS_TEST_TIME
    if signals & UNCLEAR_SIGNALS:
        return CREDENTIALS_UNCLEAR
    if signals & REPORTING_SIGNALS:
        return CREDENTIALS_REPORTING_ONLY
    return None


def test_step_signals(kind, text):
    """Whether a credential reaches the step that invokes the test suite.

    A narrower question than privilege_purpose()'s and the useful one for a
    contributor: not "is every privileged step in this scope droppable" but
    "can the test suite run without the project's secrets". Where it can, the
    tests are runnable on a contributor's own infrastructure whatever the
    publish and reporting steps around them need.

    THE ERROR DIRECTION. Where it cannot be determined whether a credential is
    reachable from the test step, the step is PRIVILEGED. That covers a step
    whose enclosing scope could not be cut out of the file and a step in a file
    that is not the whole configuration, and it is the same asymmetry
    credentials_purpose() enforces: the flattering answer must never win by
    default, so it is only ever reached by positive evidence that the step was
    identified and that nothing reaches it.

    INHERITED ENVIRONMENT IS THE TRAP. A credential mapped in at workflow level
    or job level `env:`, or in GitLab's global or job `variables:`, is in the
    environment of every step in that scope, including the test step, although
    the step itself names no secret. Ignoring that would make the figure wrong
    in the flattering direction and in bulk, since a job-level `env:` is the
    ordinary way to hand a whole job a credential. So a credential referenced
    anywhere in the step's enclosing scopes counts as available to it, and
    structure.units_with_scope() is what cuts those scopes per step rather than
    per file. Taking the whole enclosing text rather than only its `env:` and
    `variables:` blocks over-claims where an enclosing reference is not in fact
    mapped into the environment, which is this axis's direction everywhere.

    A privilege grant in the enclosing scope is NOT a credential here. A
    `permissions:` block scopes a token a step has to ask for; it puts nothing
    in the environment, and reading it as a credential would make the
    determination a restatement of the ladder.
    """
    out = set()
    incomplete = bool(kind == "gitlab"
                      and GITLAB_INHERITS_ELSEWHERE.search(text))
    for unit, enclosing in units_with_scope(kind, text):
        if not TEST_INVOCATION.search(unit):
            continue
        if enclosing is None:
            out.add(TEST_STEP_SCOPE_UNREADABLE)
            continue
        own = credential_names(unit)
        inherited = credential_names(enclosing)
        step = set()
        if own & FORGE_TOKENS or inherited & FORGE_TOKENS:
            step.add(TEST_STEP_FORGE_TOKEN)
        # Compound commands: the unit is the whole step, so a test invocation
        # sharing a shell line with a privileged act is caught by reading the
        # step whole. `npm ci && npm test` raises nothing here, which is the
        # other half of that: installing is not a privilege.
        act = base_signals(kind, unit) & (PRIVILEGE_SIGNALS - {"secret-ref"})
        if own - FORGE_TOKENS or SECRETS_INHERIT.search(unit):
            step.add(TEST_STEP_CREDENTIAL)
        if inherited - FORGE_TOKENS or SECRETS_INHERIT.search(enclosing):
            step.add(TEST_STEP_INHERITED_CREDENTIAL)
        if act or any(p.search(unit) for p in STEP_AUTHENTICATES):
            step.add(TEST_STEP_PRIVILEGED_ACT)
        # Judged per step and accumulated afterwards, so one privileged test
        # step cannot take the reading of another step in the same file away.
        # The scope-wide asymmetry is test_step_privilege()'s business.
        if not step & TEST_STEP_PRIVILEGED_SIGNALS:
            # Identified, and nothing reaches it. The one signal that can
            # answer unprivileged, and it is refused where the file is not the
            # whole configuration.
            step.add(TEST_STEP_SCOPE_INCOMPLETE if incomplete
                     else TEST_STEP_CLEAN)
        out |= step
    return out


def test_step_privilege(signals):
    """One scope's determination, which is never absent where it holds a file.

    Asked of a scope rather than a file, like credentials_purpose(), and with
    the same asymmetry: a privileged test step anywhere in the scope decides
    it, because nothing here can say which of several test invocations is the
    one a contributor would run.

    `unprivileged` is a claim about a test step that was identified and that
    nothing reaches, so it says there is a test suite a contributor could run,
    not that every step in the scope is clean. `unidentified` is the answer
    where no command form in TEST_INVOCATION was found anywhere in the scope,
    and it is deliberately not folded into either of the others: a scope whose
    tests run behind a project's own shell script is a scope this cannot read,
    which is a different statement from either answer about one it can.

    A test-time credential is decisive here as it is there, and the reason is
    the second way a credential reaches a test step. Every TEST_TIME rule
    requires the credential AND the resolution command in the same file, so
    the credential is by definition what the test invocation needs; it just
    arrives through a settings file or a credential helper an earlier step
    wrote rather than through the environment. The environment reading cannot
    see that, and without this the `mvn verify` whose registry password was
    written into settings.xml by the step before it would read as a test suite
    that runs unprivileged, which is the flattering answer and a wrong one.
    """
    if signals & (TEST_STEP_PRIVILEGED_SIGNALS | TEST_TIME_SIGNALS):
        return TEST_STEP_PRIVILEGED
    if TEST_STEP_CLEAN in signals:
        return TEST_STEP_UNPRIVILEGED
    return TEST_STEP_UNIDENTIFIED


def file_signals(path, raw):
    """The signal names one pipeline file raises."""
    kind = kind_of(path) or "actions"
    text = strip_comments(raw)
    found = base_signals(kind, text)
    return (found | privilege_purpose(kind, text, found)
            | test_step_signals(kind, text))
