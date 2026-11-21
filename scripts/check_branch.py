"""Run both GitHub workflows on the current feature branch, before it merges (AGENTS.md,
"Check Before Merging"; decided 2026-11-18 after a push to main went red in suites the
change had not touched).

    git push -u origin feature/my-branch
    .venv/bin/python scripts/check_branch.py

It starts "Publish to PyPI" (the Windows, macOS and Linux matrix; nothing is published) and
"Browser suites" on the branch's pushed commit, waits for both, and prints each failed job.
Exit status 1 when either fails. The branch must be pushed and clean: GitHub runs commits.
A release's evidence is still the push to main (scripts/release.py); this run only shows a
red run before main has it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone

WORKFLOWS = ("Publish to PyPI", "Browser suites")
MAIN = "main"
POLL_SECONDS = 30
SECONDS_PER_MINUTE = 60
# Both workflows finish in about 20 minutes when machines are free; macOS ones can be scarce.
TIMEOUT_MINUTES = 180
RUNS_LISTED = "20"
EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_NOT_READY = 2


def _output_of(*command: str) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def _runs_started_since(branch: str, commit: str, since: datetime) -> dict[str, dict[str, object]]:
    """This check's run of each workflow, once GitHub lists it: by workflow name."""
    listed = json.loads(_output_of(
        "gh", "run", "list", "--branch", branch, "--event", "workflow_dispatch", "--commit", commit,
        "--limit", RUNS_LISTED, "--json", "databaseId,workflowName,status,conclusion,createdAt",
    ))
    runs: dict[str, dict[str, object]] = {}
    for run in sorted(listed, key=lambda listed_run: listed_run["createdAt"]):
        created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
        if created >= since and run["workflowName"] in WORKFLOWS:
            runs[run["workflowName"]] = run
    return runs


def _failed_jobs(run_id: object) -> list[str]:
    jobs = json.loads(_output_of("gh", "run", "view", str(run_id), "--json", "jobs"))["jobs"]
    return [job["name"] for job in jobs if job["conclusion"] not in ("success", "skipped")]


def main() -> int:
    branch = _output_of("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch == MAIN:
        print("This checks a feature branch before it merges; main is checked by its push.")
        return EXIT_NOT_READY
    if _output_of("git", "status", "--porcelain", "--untracked-files=no") != "":
        print("Uncommitted changes: commit first. GitHub runs commits.")
        return EXIT_NOT_READY
    commit = _output_of("git", "rev-parse", "HEAD")
    # Empty when the branch was never pushed.
    pushed = _output_of("git", "for-each-ref", "--format=%(objectname)", f"refs/remotes/origin/{branch}")
    if pushed != commit:
        print(f"origin/{branch} is not at {commit}: push the branch first (git push -u origin {branch}).")
        return EXIT_NOT_READY

    since = datetime.now(timezone.utc).replace(microsecond=0)
    for workflow in WORKFLOWS:
        _output_of("gh", "workflow", "run", workflow, "--ref", branch)
    print(f"Started {' and '.join(WORKFLOWS)} on {branch} at {commit}; waiting.")

    deadline = time.monotonic() + TIMEOUT_MINUTES * SECONDS_PER_MINUTE
    while True:
        runs = _runs_started_since(branch, commit, since)
        if len(runs) == len(WORKFLOWS) and all(run["status"] == "completed" for run in runs.values()):
            break
        if time.monotonic() > deadline:
            print(f"Not finished after {TIMEOUT_MINUTES} minutes: {runs}")
            return EXIT_FAILED
        time.sleep(POLL_SECONDS)

    is_green = True
    for workflow in WORKFLOWS:
        run = runs[workflow]
        print(f"{run['conclusion'].upper():8} {workflow}  (gh run view {run['databaseId']})")
        if run["conclusion"] != "success":
            is_green = False
            for job in _failed_jobs(run["databaseId"]):
                print(f"         failed: {job}")
    if is_green:
        return EXIT_PASSED
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
