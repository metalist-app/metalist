"""Update jobs, the updater's uv and vault delete/rename jobs keep a bounded history."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import zipfile

import pytest

import app.server_runtime as server_runtime
from app.services import app_updates, update_installer
from app.services import namespace_deletion_jobs, namespace_rename_jobs

_HOUR = 3600


@pytest.fixture
def update_installation(monkeypatch, tmp_path):
    monkeypatch.setattr(app_updates, 'jobs_directory', lambda: tmp_path / 'jobs')
    monkeypatch.setattr(app_updates, 'update_executable', lambda: Path('/tools/metalist'))
    monkeypatch.setattr(app_updates, '__version__', '0.6.2')
    return tmp_path / 'jobs'


def _age(path: Path, seconds_ago: float) -> None:
    moment = time.time() - seconds_ago
    os.utime(path, (moment, moment))


def test_update_jobs_keep_the_newest_ten_pairs_and_the_active_one(update_installation):
    directory = update_installation
    created = []
    for index in range(15):
        record = app_updates.create_update_job('0.6.3')
        created.append(record['job_id'])
        Path(str(record['log_path'])).write_text('update output', encoding='utf-8')
        if index < 14:
            app_updates.write_job(dict(record, status='failed', message='Failed'))
            # Older jobs are older on disk too, one hour apart, oldest first.
            for path in (directory / f"{record['job_id']}.json", Path(str(record['log_path']))):
                _age(path, (15 - index) * _HOUR)

    remaining_jobs = {path.stem for path in directory.glob('*.json')} - {'active'}
    remaining_logs = {path.stem for path in directory.glob('*.log')}
    assert remaining_jobs == set(created[-10:])
    assert remaining_logs == set(created[-10:])
    active = json.loads((directory / 'active.json').read_text(encoding='utf-8'))
    assert active['job_id'] == created[-1]
    assert (directory / 'admission.lock').is_file()


def test_update_job_trim_never_deletes_the_job_active_json_names(update_installation):
    directory = update_installation
    newest = ''
    for index in range(10):
        record = app_updates.create_update_job('0.6.3')
        newest = record['job_id']
        app_updates.write_job(dict(record, status='failed', message='Failed'))
    active_old, plain_old = (directory / f'{uuid}.json' for uuid in (
        '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'))
    for path in (active_old, plain_old):
        path.write_text('{}', encoding='utf-8')
        _age(path, 100 * _HOUR)
    (directory / 'active.json').write_text(json.dumps({'job_id': active_old.stem}), encoding='utf-8')
    with app_updates._job_lock():
        app_updates._trim_update_jobs_locked(directory=directory, created_job_id=newest)
    assert active_old.is_file()
    assert not plain_old.exists()
    assert (directory / f'{newest}.json').is_file()


def _installer_environment(monkeypatch, tmp_path):
    binary = b'verified installer fixture'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('uv.exe', binary)
    archive_body = stream.getvalue()
    target = 'x86_64-pc-windows-msvc'
    monkeypatch.setattr(update_installer, 'INSTALLER_ARCHIVE_SHA256', {
        target: hashlib.sha256(archive_body).hexdigest(),
    })
    monkeypatch.setattr(update_installer, '_installer_target', lambda platform_name: target)
    monkeypatch.setattr(update_installer, '_download_installer_archive', lambda name: archive_body)
    monkeypatch.setattr(
        update_installer.subprocess, 'run',
        lambda command, **kwargs: SimpleNamespace(stdout=f'uv {update_installer.INSTALLER_VERSION} (fixture)\n'),
    )
    return {'LOCALAPPDATA': str(tmp_path), 'PATH': 'original-path'}, target


def test_updater_keeps_only_the_current_uv_and_fresh_staged_files(monkeypatch, tmp_path):
    environ, target = _installer_environment(monkeypatch, tmp_path)
    root = tmp_path / 'MetaList' / 'update-tools'
    current = root / f'uv-{update_installer.INSTALLER_VERSION}-{target}'
    older = root / f'uv-0.11.2-{target}'
    other_target = root / f'uv-{update_installer.INSTALLER_VERSION}-aarch64-pc-windows-msvc'
    for folder in (older, other_target):
        folder.mkdir(parents=True)
        (folder / 'uv.exe').write_bytes(b'old uv')
    current.mkdir(parents=True)
    fresh_staged = current / 'uv.exe-fresh.tmp'
    old_staged = current / 'uv.exe-old.tmp'
    fresh_staged.write_bytes(b'being written')
    old_staged.write_bytes(b'left by a failed publish')
    _age(fresh_staged, _HOUR / 2)
    _age(old_staged, 2 * _HOUR)
    unrelated = root / 'notes.txt'
    unrelated.write_text('not the updater', encoding='utf-8')

    selected = Path(update_installer.resolve_update_installer(platform_name='win32', environ=environ))

    assert selected.parent == current
    assert sorted(path.name for path in root.iterdir()) == sorted([current.name, unrelated.name])
    assert fresh_staged.is_file()
    assert not old_staged.exists()
    assert selected.is_file()


def test_updater_keeps_old_uv_folders_when_the_current_uv_fails_verification(monkeypatch, tmp_path):
    environ, target = _installer_environment(monkeypatch, tmp_path)
    older = tmp_path / 'MetaList' / 'update-tools' / f'uv-0.11.2-{target}'
    older.mkdir(parents=True)
    monkeypatch.setattr(update_installer, '_installer_version', lambda *args: (0, 12, 16))
    with pytest.raises(RuntimeError, match='wrong version'):
        update_installer.resolve_update_installer(platform_name='win32', environ=environ)
    assert older.is_dir()


@pytest.fixture
def runtime_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(server_runtime, '_DEFAULT_RUNTIME_DIRECTORY', tmp_path / 'runtime')
    return tmp_path / 'runtime'


@pytest.mark.parametrize('kind', ['delete', 'rename'])
def test_namespace_jobs_keep_the_newest_ten_and_every_running_one(runtime_directory, kind):
    if kind == 'delete':
        directory = runtime_directory / 'namespace-delete-jobs'

        def create(index):
            return namespace_deletion_jobs.create_namespace_deletion_job(
                deleted_namespace=f'vault-{index}', redirect_namespace='default')

        finish = namespace_deletion_jobs.mark_namespace_deletion_job_succeeded
        load = namespace_deletion_jobs.load_namespace_deletion_job
    else:
        directory = runtime_directory / 'namespace-rename-jobs'

        def create(index):
            return namespace_rename_jobs.create_namespace_rename_job(
                source_namespace=f'vault-{index}', target_namespace=f'renamed-{index}')

        finish = namespace_rename_jobs.mark_namespace_rename_job_succeeded
        load = namespace_rename_jobs.load_namespace_rename_job
    created = []
    for index in range(15):
        job_id = create(index)['job_id']
        created.append(job_id)
        # The second job never finishes: it is still running.
        if index != 1:
            finish(job_id=job_id)
        _age(directory / f'{job_id}.json', (15 - index) * _HOUR)

    remaining = {path.stem for path in directory.glob('*.json')}
    assert remaining == set(created[-10:]) | {created[1]}
    assert load(job_id=created[1])['status'] == 'pending'
    assert load(job_id=created[-1])['status'] == 'succeeded'
