#!/bin/sh
# The repository's own test entry point: ./test.sh
#
# No network, no credential, no host, nothing installed. Every test file takes
# the socket layer away before it does anything, so a stub that quietly fell
# through to a real forge fails here rather than spending somebody's rate
# budget from a test run.
#
# It also runs the fixture corpus, which is the review gate for a rule change:
# a rule whose real effect is a distribution over somebody else's corpus has no
# other diff.
#
# MUTATE THE CHECKS. Several of these were vacuous until somebody broke the
# thing they claimed to test and watched them pass; see CONTRIBUTING.md. The
# habit is cheap: comment out the rule, run this, and if nothing goes red the
# check is decoration.
set -u
cd "$(dirname "$0")"
PY="${PY:-python3}"

fail=0

echo "--- every Python file parses"
for f in ciprofile/*.py ciprofile/sources/*.py tests/*.py; do
  if "$PY" -c "import ast,sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])" "$f"
  then :; else echo "  FAIL  $f does not parse"; fail=1; fi
done
echo "  ok    $(ls ciprofile/*.py ciprofile/sources/*.py tests/*.py | wc -l | tr -d ' ') files"

echo "--- every module imports with no credentials and no network"
for m in structure rules classify sweep cache report fixtures fork_observation \
         differential sources sources.base sources.forgejo sources.gitlab \
         sources.github sources.local; do
  if env -u FORGE_URL -u FORGE_TOKEN -u GITLAB_URL -u GITHUB_TOKEN \
       -u GH_TOKEN "$PY" -c "import ciprofile.$m" >/dev/null 2>&1
  then echo "  ok    ciprofile.$m"
  else echo "  FAIL  ciprofile.$m"; fail=1; fi
done

echo "--- the entry points refuse cleanly when unconfigured"
for args in "--source forgejo" "--source gitlab" "--source github" \
            "--source local"; do
  out=$(env -u FORGE_URL -u FORGE_TOKEN -u GITLAB_URL -u GITHUB_TOKEN \
        -u GH_TOKEN "$PY" -m ciprofile $args 2>&1); rc=$?
  case "$rc:$out" in
    0:*)         echo "  FAIL  $args exits zero when unconfigured"; fail=1 ;;
    *Traceback*) echo "  FAIL  $args refuses with a traceback"; fail=1 ;;
    *)           echo "  ok    $args refuses cleanly" ;;
  esac
done

echo "--- differential execution refuses before it executes anything"
# The one mode that runs third-party code. Both refusals are checked from the
# command line as well as from the unit checks, because this is the spelling a
# person actually types and it must not get as far as a container.
for args in "" "--profile /nonexistent --cache /nonexistent" \
            "--profile /nonexistent --cache /nonexistent --sample 9999"; do
  out=$("$PY" -m ciprofile.differential $args 2>&1); rc=$?
  case "$rc:$out" in
    0:*)         echo "  FAIL  differential '$args' exits zero"; fail=1 ;;
    *Traceback*) echo "  FAIL  differential '$args' refuses with a traceback"
                 fail=1 ;;
    *)           echo "  ok    differential '${args:-no arguments}' refuses" ;;
  esac
done

echo "--- the fixture corpus"
if "$PY" -m ciprofile --fixtures >/dev/null; then
  echo "  ok    $("$PY" -m ciprofile --fixtures | tail -1)"
else
  "$PY" -m ciprofile --fixtures | tail -20; fail=1
fi

for t in tests/test_*.py; do
  echo "--- $t"
  "$PY" "$t" || fail=1
done

echo
if [ "$fail" -eq 0 ]; then
  echo "PASS"
else
  echo "FAIL"
fi
exit "$fail"
