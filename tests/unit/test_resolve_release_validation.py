from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/resolve_release_validation.py"
SPEC = importlib.util.spec_from_file_location("resolve_release_validation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_publisher_and_local_release_driver_require_the_same_main_matrix() -> None:
    release_script = SCRIPT.with_name("release.py")
    release_spec = importlib.util.spec_from_file_location("release_driver_for_gate_test", release_script)
    assert release_spec is not None and release_spec.loader is not None
    release_driver = importlib.util.module_from_spec(release_spec)
    release_spec.loader.exec_module(release_driver)
    assert gate.expected_main_jobs() == release_driver.expected_jobs(publish_conclusion="skipped")


def test_main_gate_requires_every_platform_job_and_skipped_publish() -> None:
    expected = gate.expected_main_jobs()
    assert len(expected) == 25
    gate.validate_main_jobs([
        {"name": name, "conclusion": conclusion}
        for name, conclusion in expected.items()
    ])
    missing = [
        {"name": name, "conclusion": conclusion}
        for name, conclusion in expected.items()
        if name != "Package and update (windows-latest, 3.14)"
    ]
    with pytest.raises(gate.ReleaseValidationError, match="incomplete"):
        gate.validate_main_jobs(missing)


def test_main_gate_requires_exact_commit_identity() -> None:
    valid = {
        "id": 42,
        "head_sha": "abc123",
        "head_branch": "main",
        "event": "push",
        "name": gate.WORKFLOW_NAME,
        "path": f".github/workflows/{gate.WORKFLOW}",
        "head_repository": {"full_name": "metalist-app/metalist"},
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }
    assert gate.select_main_run(
        [valid], repository="metalist-app/metalist", commit="abc123",
    ) == valid
    with pytest.raises(gate.ReleaseValidationError, match="found 0"):
        gate.select_main_run(
            [dict(valid, head_sha="other")],
            repository="metalist-app/metalist", commit="abc123",
        )
    # A later attempt is selected; its earlier attempts are checked separately.
    assert gate.select_main_run(
        [dict(valid, run_attempt=2)], repository="metalist-app/metalist", commit="abc123",
    )["run_attempt"] == 2


NEVER_STARTED = {"name": "Python (macos-latest, 3.11)", "conclusion": "cancelled", "runner_id": 0, "runner_name": "", "steps": []}
RAN_AND_FAILED = {"name": "Browser smoke (Linux Chrome and Firefox)", "conclusion": "failure", "runner_id": 7,
                  "runner_name": "GitHub Actions 7", "steps": [{"name": "Run"}]}
PASSED = {"name": "build", "conclusion": "success", "runner_id": 7, "runner_name": "GitHub Actions 7", "steps": [{"name": "Run"}]}


def test_an_earlier_attempt_may_only_have_jobs_github_never_started() -> None:
    gate.check_earlier_attempts({1: [PASSED, NEVER_STARTED]})
    with pytest.raises(gate.ReleaseValidationError, match="ran and failed"):
        gate.check_earlier_attempts({1: [PASSED, RAN_AND_FAILED]})
    # Cancelled after it started (a timeout) is a failure too.
    with pytest.raises(gate.ReleaseValidationError, match="ran and failed"):
        gate.check_earlier_attempts({1: [dict(RAN_AND_FAILED, conclusion="cancelled")]})


def test_publisher_and_local_release_driver_agree_on_jobs_that_never_started() -> None:
    release_script = SCRIPT.with_name("release.py")
    release_spec = importlib.util.spec_from_file_location("release_driver_for_attempts", release_script)
    assert release_spec is not None and release_spec.loader is not None
    release_driver = importlib.util.module_from_spec(release_spec)
    release_spec.loader.exec_module(release_driver)
    for job in (NEVER_STARTED, RAN_AND_FAILED, PASSED, dict(NEVER_STARTED, runner_id=None, runner_name=None),
                dict(RAN_AND_FAILED, conclusion="cancelled")):
        assert gate.never_started(job) == release_driver.never_started(job), job


def test_main_gate_rejects_artifact_from_another_commit() -> None:
    artifact = {
        "name": "pypi-distributions",
        "expired": False,
        "workflow_run": {"id": 42, "head_sha": "different"},
    }
    with pytest.raises(gate.ReleaseValidationError, match="another workflow"):
        gate.validate_artifact([artifact], run_id=42, commit="abc123")


def test_tag_and_downloaded_files_must_match(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    assert gate.validate_tag_version(root=tmp_path, tag="v1.2.3") == "1.2.3"
    with pytest.raises(gate.ReleaseValidationError, match="does not match"):
        gate.validate_tag_version(root=tmp_path, tag="v1.2.4")
    distributions = tmp_path / "dist"
    distributions.mkdir()
    (distributions / "metalist-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (distributions / "metalist-1.2.3.tar.gz").write_bytes(b"sdist")
    gate.check_distributions(directory=distributions, version="1.2.3")
    (distributions / "extra.txt").write_text("wrong", encoding="utf-8")
    with pytest.raises(gate.ReleaseValidationError, match="do not match"):
        gate.check_distributions(directory=distributions, version="1.2.3")
