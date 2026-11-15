#!/bin/bash
# Runs browser suites on Linux, as GitHub's "Browser suites" workflow does, in a Docker container:
# Linux fonts, Python 3.12, Node 22, Firefox 160 and Chromium (Google Chrome has no arm64 Linux
# build; the font metrics are what differ from macOS). The repository is mounted read-only and
# copied in (committed and changed files), so this checkout's node_modules and .venv are untouched.
#
#   scripts/linux-ci/run-suites.sh chrome edit-locks list-edges
#   scripts/linux-ci/run-suites.sh firefox --shard 5/10      # one of GitHub's slices, 2 at a time
#
# Needs Docker Desktop running. Prints one line per suite, and the log tail of each that failed.
set -euo pipefail
browser="$1"; shift
repository="$(cd "$(dirname "$0")/../.." && pwd)"
image=metalist-ci-linux
docker build -q -t "$image" "$repository/scripts/linux-ci" > /dev/null
# Chromium's sandbox needs user namespaces, which Docker's default seccomp profile blocks.
docker run --rm --shm-size=2g --security-opt seccomp=unconfined -v "$repository":/src:ro "$image" bash -c '
  set -euo pipefail
  cd /src && git config --global --add safe.directory /src
  git ls-files -z --cached --others --exclude-standard | rsync -a --from0 --files-from=- /src/ /home/runner/work/metalist/
  cd /home/runner/work/metalist
  python -m venv .venv && .venv/bin/python -m pip install -q --require-hashes -r requirements/ci.txt > /dev/null
  npm ci --ignore-scripts --no-audit --no-fund > /dev/null 2>&1
  browser="$1"; shift
  if [ "${1:-}" = "--shard" ]; then
    node scripts/run-browser-suites.mjs --browser "$browser" --workers 2 --shard "$2"
    exit
  fi
  failed=0
  for suite in "$@"; do
    if out=$(BROWSER_TEST_BROWSER="$browser" BROWSER_TEST_SUITE="$suite" node scripts/browser-smoke.mjs 2>&1); then
      echo "PASS $suite"
    else
      echo "FAIL $suite"; echo "$out" | grep -vE "node_modules|dbus" | tail -15; failed=1
    fi
  done
  exit $failed
' bash "$browser" "$@"
