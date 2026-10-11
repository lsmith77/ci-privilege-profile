#!/usr/bin/env python3
"""Where pipelines live, and how their text is cut into the units a rule asks of.

Two readings of the same files live here, and knowing which one ran matters:

  - A LINE READER. Regex plus indentation-aware extraction, stdlib only. It is
    what the fetching side has always been able to rely on, and it is the
    fallback whenever the parser below is unavailable or the file will not
    parse.
  - A REAL PARSER, optional. Where PyYAML is importable the document is
    composed into a node tree and the units are cut on the parser's own line
    marks, so the *text* each rule sees is still verbatim; only the structure
    comes from the parser.

The second exists because the first cost a measured defect. A `steps:` block
whose list items sit at the key's own column is legal YAML, and the line reader
read it as an empty block: every privilege in such a job became unattributable,
in 81 of 505 pull-request-scope files in the corpus where it was found. See
EXPERIMENTS.md, "A hand-rolled block parser, and what it cost". The lesson
recorded there is the one this module is shaped around: the no-dependency
constraint belongs to the fetching side, which runs in a container, not to the
analysis side, which runs on a laptop.

The line reader has since been taught that one shape, so the two agree on every
fixture, which is asserted by the test suite rather than assumed. Where they
can still differ is the long tail: the parser reads `on:` shapes and `script:`
spellings the line reader does not, so the fallback declares a trigger
undeterminable more often. An undeterminable trigger puts a file in the
pull-request scope, which is the over-claiming direction, so the fallback is
never the more flattering of the two.
"""
import re

# Workflow directories, in Forgejo's own fallback order. `.github/workflows`
# is last and is nonetheless where most of any real corpus's pipelines are.
WORKFLOW_DIRS = (".forgejo/workflows", ".gitea/workflows", ".github/workflows")
GITLAB_FILE = ".gitlab-ci.yml"
WORKFLOW_EXT = (".yml", ".yaml")

# CI definitions that exist, are not read here, and must therefore stop
# `no-pipeline` from being read as "no CI". Root-level markers only: the root
# listing is already being fetched, so collecting them is free.
OTHER_CI = {
    ".travis.yml", ".travis.yaml", "jenkinsfile", ".drone.yml", ".drone.star",
    ".woodpecker.yml", ".woodpecker.yaml", ".woodpecker", ".circleci",
    "azure-pipelines.yml", "azure-pipelines.yaml", "appveyor.yml",
    ".appveyor.yml", "bitbucket-pipelines.yml", ".cirrus.yml", ".builds",
    ".semaphore", "codemagic.yaml", "wercker.yml", "cloudbuild.yaml",
    "buildkite.yml", ".buildkite", "bitrise.yml", "shippable.yml",
    # Not a typo: GitLab reads `.gitlab-ci.yml` and nothing else by default,
    # so the .yaml spelling is a definition no forge runs.
    ".gitlab-ci.yaml",
}

# ---------------------------------------------------------------- the parser

try:                                  # optional, and only for analysis
    import yaml as _yaml
except ImportError:                   # pragma: no cover - environment-dependent
    _yaml = None


def parser_available():
    """Whether the structural reading has a real parser behind it.

    Reported in every output. A figure produced without the parser and one
    produced with it are not quite the same measurement, and a reader must not
    have to guess which they are holding.
    """
    return _yaml is not None


def _compose(text):
    """The document's node tree, or None if it will not parse.

    `compose` rather than `safe_load`: it keeps every scalar as the raw string
    it was written as, and it carries line marks, which is the whole reason for
    using it. Nothing here evaluates a tag, so no constructor runs and no
    arbitrary object can be instantiated from the document.
    """
    if _yaml is None:
        return None
    try:
        return _yaml.compose(text)
    except Exception:
        # Deliberately everything. A pipeline file is somebody else's input: a
        # tab, a duplicate anchor, an unresolvable alias or a shape this
        # parser version dislikes must cost the parser's reading of that one
        # file and nothing more.
        return None


def _is_map(node):
    return _yaml is not None and isinstance(node, _yaml.nodes.MappingNode)


def _is_seq(node):
    return _yaml is not None and isinstance(node, _yaml.nodes.SequenceNode)


def _is_scalar(node):
    return _yaml is not None and isinstance(node, _yaml.nodes.ScalarNode)


def _entry(node, want):
    """The value node under one mapping key, matched case-sensitively.

    `on:` is why the key is taken from the node's own `value` rather than from
    its resolved tag: YAML 1.1 reads a bare `on` as a boolean, so an emitter
    writes `"on":` and a loader hands back `True`. The written text is what
    this needs.
    """
    if not _is_map(node):
        return None
    for key, value in node.value:
        if _is_scalar(key) and key.value == want:
            return value
    return None


def _span(lines, start, stop):
    """The text of lines[start:stop], as one block, trailing blanks dropped."""
    block = lines[start:stop]
    while block and not block[-1].strip():
        block.pop()
    return "\n".join(block)


def _item_spans(items, end):
    """(start, stop) line spans for a sequence's items.

    Each item runs to the start of the next one rather than to its own
    `end_mark`, so whatever sits between two items (a blank line, anything the
    comment stripper left) belongs to the item it follows. That is the line
    reader's behaviour too, and the two readings have to agree.
    """
    starts = [item.start_mark.line for item in items]
    return [(s, starts[i + 1] if i + 1 < len(starts) else end)
            for i, s in enumerate(starts)]


def _node_end(node):
    """The line after a node's last line."""
    mark = node.end_mark
    return mark.line + 1 if mark.column else mark.line


def _walk(node):
    """Every node in the tree.

    Needed because the same readings are asked of a whole document and of a
    single step cut out of one: a step fragment composes to a one-item
    sequence, so anything that only looked under `jobs:` would find nothing in
    it and silently answer "no script here". For the github-script rules, that
    is the difference between a forge write and a reporting step.
    """
    stack = [node]
    while stack:
        n = stack.pop()
        if n is None:
            continue
        yield n
        if _is_map(n):
            stack += [v for _k, v in n.value]
        elif _is_seq(n):
            stack += list(n.value)


# ---------------------------------------------------------------- text helpers

COMMENT_LINE = re.compile(r"^[ \t]*#")


def strip_comments(text):
    """Drop whole-line comments.

    Cheap and worth it: a commented-out `docker push` and a live one are the
    same string to every regex in rules.py, and a disabled job left in a
    workflow is the most common way a repository reads as more privileged than
    it is. A trailing comment on a line that carries content is left alone:
    removing it would need to know whether the `#` is inside a quoted string.
    """
    return "\n".join(l for l in text.splitlines() if not COMMENT_LINE.match(l))


def kind_of(path):
    """"gitlab" | "actions" | None: which grammar a file is written in.

    The path decides, not the content: the same YAML means different things in
    `.github/workflows/` and at `.gitlab-ci.yml`, and a rule that applies to
    one grammar would misfire on the other.
    """
    # Not lstrip("./"): that strips a character set, so ".github/..." loses its
    # leading dot and stops matching the directory it names.
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = "/" + p.lstrip("/")
    if p.endswith("/" + GITLAB_FILE):
        return "gitlab"
    for d in WORKFLOW_DIRS:
        if ("/" + d + "/") in p and p.endswith(WORKFLOW_EXT):
            return "actions"
    return None


# ---------------------------------------------------- the line reader's keys

BLOCK_INDICATOR = re.compile(r"^[|>][+-]?\d*$")
RUN_KEY = re.compile(r"^(?P<pre>[ \t]*(?:-[ \t]+)?)run:(?P<rest>.*)$")
SCRIPT_KEY = re.compile(
    r"^(?P<ind>[ \t]*)(?:before_script|after_script|script):(?P<rest>.*)$")
# The same word as an Actions action input, where its value is JavaScript
# rather than a list of shell commands.
ACTIONS_SCRIPT_KEY = re.compile(r"^(?P<ind>[ \t]*)script:(?P<rest>.*)$")
# `on:` at the top level of a workflow, in the spellings that occur: bare, and
# the quoted forms YAML 1.1's boolean `on` makes some emitters produce. Top
# level only, which is what anchors it: an `on:` nested inside a `with:` block
# is an action's input, and a `pull_request_target` inside a `run:` step is a
# string, neither of them this workflow's trigger.
ON_KEY = re.compile(r"""^(?:on|'on'|"on"):(?P<rest>.*)$""")
TRIGGER_NAME = re.compile(r"[a-z_][a-z0-9_]*")
# A `steps:` block and the list items in it. Everything the purpose axis asks
# is asked of one step, so the step is the unit and the rest of the file is the
# frame.
STEPS_KEY = re.compile(r"^(?P<ind>[ \t]*)steps:[ \t]*$")
LIST_ITEM = re.compile(r"^(?P<ind>[ \t]*)-[ \t]+\S")
# A GitLab job is the unit instead: its `script:` is a list of commands rather
# than of steps with their own keys, and the job is the smallest thing that can
# be dropped on its own. These top-level keys are not jobs.
GITLAB_GLOBAL_KEY = re.compile(
    r"^(?:stages|variables|include|default|workflow|image|services|cache"
    r"|before_script|after_script|types):")
TOP_LEVEL_KEY = re.compile(r"""^["'.A-Za-z_][^:\n]*:""")
# A `script:` value that only points at the script rather than being it, so
# there is no body here to read.
SCRIPT_INDIRECT = re.compile(r"^(?:\$\{\{.*\}\}|[*&]\S+)$")

# The triggers a contributor's own pull request sets off, plus the reusable
# workflow, which is in scope because the file cannot say who calls it.
PR_TRIGGERS = {"pull_request", "pull_request_target", "workflow_call"}


def _block_body(lines, i, key_col, seq=False):
    """Lines belonging to a block opened at lines[i], dedented.

    `seq` admits a sequence written at the key's own column, which is what YAML
    allows for a list under a mapping key. Without it such a block reads as
    empty, and an empty block is the worst possible answer for attribution:
    every privilege in the job lands in the frame, where no step can be held
    responsible for it, so a workflow whose steps are simply unindented reads
    as holding a privilege nobody uses.

    Off by default rather than applied everywhere, because each caller's key
    takes a different kind of value and the reading has to be judged per
    caller. For a `run:` block scalar it is moot: a `- run:` key always sits
    deeper than the dash that opened its own step, so no sibling item can be at
    its column.
    """
    body, j = [], i + 1
    while j < len(lines):
        line = lines[j]
        indent = len(line) - len(line.lstrip())
        if line.strip() and (indent < key_col or (
                indent == key_col
                and not (seq and LIST_ITEM.match(line)))):
            break
        body.append(line[key_col:] if len(line) > key_col else "")
        j += 1
    return body, j


def _trigger_set(candidates):
    """Trigger names out of candidate strings, or None if none is a name."""
    names = {s.strip().strip("'\"").lower() for s in candidates}
    return {n for n in names if TRIGGER_NAME.fullmatch(n)} or None


# ---------------------------------------------------------------- triggers

def actions_triggers(text):
    """The trigger names a workflow declares, or None if `on:` cannot be read.

    None is not "no triggers". It is "this file did not say so in a shape
    either reading handles", and every caller takes it the privileged way
    rather than the flattering one: in scope, and without the
    `pull_request_target` flag.

    The parser answers wherever it can, because the shapes `on:` comes in are
    exactly the kind of long tail a regex loses. The line reader handles the
    shapes that occur: `on: pull_request`, `on: [push, pull_request]`, a block
    mapping, that block with `types:` nested one deeper, a block written as a
    `- push` sequence, and the quoted `"on":`.
    """
    node = _compose(text)
    if node is not None:
        value = _entry(node, "on")
        if _is_scalar(value):
            return _trigger_set([value.value])
        if _is_seq(value):
            return _trigger_set([i.value for i in value.value
                                 if _is_scalar(i)])
        if _is_map(value):
            return _trigger_set([k.value for k, _ in value.value
                                 if _is_scalar(k)])
        if value is not None:
            return None
        # A composed document with no `on:` key has genuinely declared no
        # trigger, and saying so is more than the line reader can: a workflow
        # file without one runs nothing. It is still reported as
        # undeterminable, because that is the reading that keeps the file in
        # the pull-request scope, and a file this says nothing about is not a
        # file to quietly drop out of the quoted figure.
        return None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = ON_KEY.match(line)
        if not m:
            continue
        # A trailing comment is still on the line (strip_comments() only drops
        # whole-line ones), and no trigger name can hold a `#`.
        rest = m.group("rest").split("#", 1)[0].strip()
        if rest[:1] in ("[", "{"):
            # A flow collection, where an entry's name is whatever precedes a
            # colon: `on: [push, pull_request]`, `on: {pull_request: null}`.
            inner = rest[1:-1] if rest[-1:] in ("]", "}") else rest[1:]
            return _trigger_set(p.split(":", 1)[0] for p in inner.split(","))
        if rest:
            return _trigger_set([rest])                      # `on: push`
        # A block, mapping or sequence. Only its own first level holds trigger
        # names: a `types:` under `pull_request:` is one indent deeper.
        body, _ = _block_body(lines, i, 0)
        depth, items = None, []
        for b in body:
            if not b.strip():
                continue
            indent = len(b) - len(b.lstrip())
            if depth is None:
                depth = indent
            if indent == depth:
                items.append(
                    re.sub(r"^-[ \t]*", "", b.strip()).split(":", 1)[0])
        return _trigger_set(items)
    return None


def in_pull_request_scope(path, raw):
    """Whether a contributor's own pull request would run this file.

    A GitLab file is in scope whole. Deciding one job's reachability on a merge
    request means evaluating its `rules:` / `only:` / `except:` against the
    event and following `extends:` and `include:` (more than a single file's
    text supports), so the whole file is taken as in scope and a GitLab
    repository over-claims its pull-request scope wherever its deploy job is
    branch-gated.
    """
    if kind_of(path) == "gitlab":
        return True
    triggers = actions_triggers(strip_comments(raw))
    return triggers is None or bool(triggers & PR_TRIGGERS)


# ---------------------------------------------------------------- commands

def _actions_run_bodies(node):
    """Every step's `run:` value, off the parser."""
    out = []
    for _job, steps, _start, _stop in _actions_step_nodes(node):
        for step in steps:
            run = _entry(step, "run")
            if _is_scalar(run):
                out.append(run.value)
    return out


def actions_commands(text):
    """Every `run:` step's command text, one entry per step.

    What the shape test (`thin-wrapper`) is computed over: one entry here is
    one thing a contributor would have to be able to run by hand.
    """
    node = _compose(text)
    if node is not None:
        return _actions_run_bodies(node)
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = RUN_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        col = len(m.group("pre"))
        rest = m.group("rest").strip()
        if BLOCK_INDICATOR.match(rest):
            body, i = _block_body(lines, i, col)
            out.append("\n".join(body))
        else:
            out.append(rest)
            i += 1
    return out


def actions_script_bodies(text):
    """Every readable `script:` action-input value, one entry per key.

    Not gitlab_commands(): there `script:` is a job's list of shell commands,
    here it is an action input whose value is JavaScript.

    A key whose value is not the script (an interpolation that assembles it
    elsewhere, a YAML alias, or a shape not handled here) contributes nothing,
    so an empty result means "no body could be isolated" and not "the body is
    empty". Callers have to tell those apart, and they pull in opposite
    directions: see rules.github_script_writes() against
    rules.github_script_reports().
    """
    node = _compose(text)
    if node is not None:
        out = []
        # Every `with:` block anywhere in the tree, because this is asked of a
        # single step as often as of a whole workflow; see _walk().
        for n in _walk(node):
            with_block = _entry(n, "with")
            script = _entry(with_block, "script") \
                if with_block is not None else None
            if _is_scalar(script) and not SCRIPT_INDIRECT.match(
                    script.value.strip()):
                out.append(script.value)
        return out
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = ACTIONS_SCRIPT_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        col = len(m.group("ind"))
        rest = m.group("rest").strip()
        if BLOCK_INDICATOR.match(rest):
            body, i = _block_body(lines, i, col)
            out.append("\n".join(body))
            continue
        if rest and not SCRIPT_INDIRECT.match(rest):
            out.append(rest.strip("'\""))
        i += 1
    return out


def gitlab_commands(text):
    """Every `script:` / `before_script:` / `after_script:` entry.

    GitLab's shape is a list of commands rather than a list of steps, so each
    list item is one "step" for the shape test. That is the right reading: an
    item is exactly one shell command line.
    """
    node = _compose(text)
    if node is not None:
        out = []
        # Every mapping in the tree, which matches what the line reader does:
        # it matches the key wherever it appears, so a `default:` block's
        # `before_script` counts for both readings.
        for key in ("script", "before_script", "after_script"):
            for holder in _walk(node):
                value = _entry(holder, key)
                if _is_scalar(value):
                    out.append(value.value)
                elif _is_seq(value):
                    out += [i.value for i in value.value if _is_scalar(i)]
        return out
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = SCRIPT_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        col = len(m.group("ind"))
        rest = m.group("rest").strip()
        if rest and not BLOCK_INDICATOR.match(rest):
            # `script: make test`, or a flow sequence `script: [a, b]`.
            if rest.startswith("[") and rest.endswith("]"):
                out += [p.strip().strip("'\"")
                        for p in rest[1:-1].split(",") if p.strip()]
            else:
                out.append(rest.strip("'\""))
            i += 1
            continue
        body, i = _block_body(lines, i, col)
        if BLOCK_INDICATOR.match(rest):
            out.append("\n".join(body))
            continue
        j = 0
        while j < len(body):
            item = body[j]
            im = re.match(r"^[ \t]*-[ \t]*(.*)$", item)
            if not im:
                j += 1
                continue
            val = im.group(1).strip()
            if BLOCK_INDICATOR.match(val):
                sub, j = _block_body(body, j, len(item) - len(item.lstrip()))
                out.append("\n".join(sub))
                continue
            out.append(val.strip("'\""))
            j += 1
    return out


def commands(path, raw):
    """One file's command list, in whichever grammar its path says it is in."""
    return (gitlab_commands(raw) if kind_of(path) == "gitlab"
            else actions_commands(raw))


# ------------------------------------------------------------ privilege units

def _actions_step_nodes(node):
    """[(job name, [step nodes], steps start line, steps end line)].

    `jobs:` at the top level only, which is where a workflow's jobs are. A
    `steps:` key anywhere else is somebody's action input.
    """
    out = []
    jobs = _entry(node, "jobs")
    if not _is_map(jobs):
        return out
    for name, job in jobs.value:
        steps = _entry(job, "steps")
        if not _is_seq(steps):
            continue
        out.append((name.value if _is_scalar(name) else "?",
                    list(steps.value),
                    steps.start_mark.line, _node_end(steps)))
    return out


def actions_steps(text):
    """([one text per step], everything outside every `steps:` block).

    A privilege in the frame (a job-level `env:`, a `permissions:` block)
    cannot be attributed to a step at all, and rules.privilege_purpose() takes
    that as the unattributable case rather than guessing which step it was
    meant for. That is why the frame is returned beside the steps instead of
    being thrown away.
    """
    lines = text.splitlines()
    node = _compose(text)
    if node is not None:
        steps, used = [], set()
        for _job, items, start, stop in _actions_step_nodes(node):
            used.update(range(start, stop))
            for s, e in _item_spans(items, stop):
                steps.append(_span(lines, s, e))
        frame = [l for n, l in enumerate(lines) if n not in used]
        return steps, "\n".join(frame)
    # The block is read with `seq=True`, so a `steps:` whose items sit at its
    # own column yields those steps rather than nothing. That is the shape
    # that cost a measured defect; see the module docstring.
    steps, used, i = [], set(), 0
    while i < len(lines):
        m = STEPS_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        col = len(m.group("ind"))
        body, end = _block_body(lines, i, col, seq=True)
        used.update(range(i, end))
        item_col, cur = None, []
        for b in body:
            indent = len(b) - len(b.lstrip())
            if LIST_ITEM.match(b) and item_col in (None, indent):
                item_col = indent
                if cur:
                    steps.append("\n".join(cur))
                cur = [b]
            elif cur:
                cur.append(b)
        if cur:
            steps.append("\n".join(cur))
        i = end
    frame = [l for n, l in enumerate(lines) if n not in used]
    return steps, "\n".join(frame)


def gitlab_jobs(text):
    """([one text per job], the global keys outside them)."""
    lines = text.splitlines()
    node = _compose(text)
    if node is not None and _is_map(node):
        tops = [(k, v) for k, v in node.value if _is_scalar(k)]
        starts = [k.start_mark.line for k, _ in tops]
        jobs, frame = [], list(lines[:starts[0]] if starts else lines)
        for n, (key, _value) in enumerate(tops):
            start = starts[n]
            stop = starts[n + 1] if n + 1 < len(tops) else len(lines)
            if GITLAB_GLOBAL_KEY.match(key.value + ":"):
                frame += lines[start:stop]
            else:
                jobs.append(_span(lines, start, stop))
        return jobs, "\n".join(frame)
    starts = [i for i, l in enumerate(lines) if TOP_LEVEL_KEY.match(l)]
    if not starts:
        return [], text
    jobs, frame = [], lines[:starts[0]]
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        if GITLAB_GLOBAL_KEY.match(lines[i]):
            frame += lines[i:end]
        else:
            jobs.append("\n".join(lines[i:end]))
    return jobs, "\n".join(frame)


def privilege_units(kind, text):
    """The things a rule can ask its question of, and what is left over."""
    return gitlab_jobs(text) if kind == "gitlab" else actions_steps(text)
