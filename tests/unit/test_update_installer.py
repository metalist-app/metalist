import hashlib
import io
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

from app.services import update_installer
from scripts.build_windows_update_repair import build_repair_archive


def _archive(*, member_name: str, binary: bytes, archive_format: str) -> bytes:
    stream = io.BytesIO()
    if archive_format == "zip":
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(member_name, binary)
    else:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            member = tarfile.TarInfo(member_name)
            member.size = len(binary)
            archive.addfile(member, io.BytesIO(binary))
    return stream.getvalue()


@pytest.fixture
def managed_installer_fixture(monkeypatch, tmp_path):
    binary = b"verified installer fixture"
    archive_body = _archive(member_name="uv.exe", binary=binary, archive_format="zip")
    target = "x86_64-pc-windows-msvc"
    asset_name = f"uv-{target}.zip"
    monkeypatch.setattr(update_installer, "INSTALLER_ARCHIVE_SHA256", {
        target: hashlib.sha256(archive_body).hexdigest(),
    })
    monkeypatch.setattr(update_installer, "_installer_target", lambda platform_name: target)
    downloads = []

    def download(name):
        downloads.append(name)
        return archive_body

    monkeypatch.setattr(update_installer, "_download_installer_archive", download)
    environ = {"LOCALAPPDATA": str(tmp_path), "PATH": "original-path"}
    return environ, binary, archive_body, asset_name, downloads


@pytest.mark.parametrize(
    ("platform_name", "machine", "libc_name", "expected"),
    [
        ("win32", "AMD64", "", "x86_64-pc-windows-msvc"),
        ("win32", "ARM64", "", "aarch64-pc-windows-msvc"),
        ("darwin", "x86_64", "", "x86_64-apple-darwin"),
        ("darwin", "arm64", "", "aarch64-apple-darwin"),
        ("linux", "x86_64", "glibc", "x86_64-unknown-linux-gnu"),
        ("linux", "aarch64", "musl", "aarch64-unknown-linux-musl"),
    ],
)
def test_installer_target_matches_operating_system_architecture_and_libc(
    monkeypatch, platform_name, machine, libc_name, expected,
):
    monkeypatch.setattr(update_installer.platform, "machine", lambda: machine)
    monkeypatch.setattr(update_installer.platform, "libc_ver", lambda: (libc_name, "fixture"))
    assert update_installer._installer_target(platform_name) == expected


def test_unsupported_installer_target_fails_loudly(monkeypatch):
    monkeypatch.setattr(update_installer.platform, "machine", lambda: "mips64")
    with pytest.raises(RuntimeError, match="Unsupported .* updater platform"):
        update_installer._installer_target("linux")


@pytest.mark.parametrize(
    ("platform_name", "directory_variable", "relative_parts"),
    [
        ("win32", "LOCALAPPDATA", ("MetaList", "update-tools")),
        ("darwin", "HOME", ("Library", "Caches", "MetaList", "update-tools")),
        ("linux", "XDG_CACHE_HOME", ("metalist", "update-tools")),
        ("linux", "HOME", (".cache", "metalist", "update-tools")),
    ],
)
def test_managed_installer_uses_operating_system_user_cache(
    tmp_path, platform_name, directory_variable, relative_parts,
):
    user_directory = tmp_path / directory_variable.casefold()
    cache_root = update_installer._installer_cache_root(
        platform_name=platform_name, environ={directory_variable: str(user_directory)},
    )
    assert cache_root == user_directory.joinpath(*relative_parts)


@pytest.mark.parametrize("platform_name", ["win32", "darwin", "linux"])
def test_update_always_selects_managed_verified_installer(monkeypatch, platform_name):
    monkeypatch.setattr(
        update_installer, "_managed_installer",
        lambda **kwargs: f"managed-{platform_name}-uv",
    )
    monkeypatch.setattr(
        update_installer, "_installer_version",
        lambda executable, environ: tuple(
            int(part) for part in update_installer.INSTALLER_VERSION.split(".")
        ),
    )
    cleanups = []
    monkeypatch.setattr(
        update_installer, "_remove_superseded_installer_files",
        lambda **kwargs: cleanups.append(kwargs),
    )
    assert update_installer.resolve_update_installer(
        platform_name=platform_name, environ={"PATH": "user-tools"},
    ) == f"managed-{platform_name}-uv"
    assert cleanups == [{
        "executable": Path(f"managed-{platform_name}-uv"), "platform_name": platform_name,
        "environ": {"PATH": "user-tools"},
    }]


def test_managed_installer_downloads_once_and_revalidates_cached_bytes(
    monkeypatch, managed_installer_fixture,
):
    environ, binary, archive_body, asset_name, downloads = managed_installer_fixture
    monkeypatch.setattr(
        update_installer.subprocess, "run",
        lambda command, **kwargs: SimpleNamespace(
            stdout=f"uv {update_installer.INSTALLER_VERSION} (fixture)\n",
        ),
    )
    selected = Path(update_installer.resolve_update_installer(
        platform_name="win32", environ=environ,
    ))
    assert selected.read_bytes() == binary
    assert next(selected.parent.glob("*.zip")).read_bytes() == archive_body
    assert downloads == [asset_name]
    assert environ["PATH"] == "original-path"
    assert update_installer.resolve_update_installer(
        platform_name="win32", environ=environ,
    ) == str(selected)
    assert downloads == [asset_name]


def test_posix_tar_archive_installs_executable_with_private_permissions(monkeypatch, tmp_path):
    binary = b"posix uv fixture"
    target = "aarch64-apple-darwin"
    archive_body = _archive(
        member_name=f"uv-{target}/uv", binary=binary, archive_format="tar",
    )
    monkeypatch.setattr(update_installer, "INSTALLER_ARCHIVE_SHA256", {
        target: hashlib.sha256(archive_body).hexdigest(),
    })
    monkeypatch.setattr(update_installer, "_installer_target", lambda platform_name: target)
    monkeypatch.setattr(update_installer, "_download_installer_archive", lambda name: archive_body)
    real_chmod = update_installer.os.chmod
    chmod_calls = []

    def record_chmod(path, mode):
        chmod_calls.append((Path(path), mode))
        real_chmod(path, mode)

    monkeypatch.setattr(update_installer.os, "chmod", record_chmod)
    selected = Path(update_installer._managed_installer(
        platform_name="darwin", environ={"HOME": str(tmp_path)},
    ))
    assert selected.read_bytes() == binary
    assert selected.name == "uv"
    assert (selected, 0o700) in chmod_calls
    if os.name != "nt":
        assert selected.stat().st_mode & 0o777 == 0o700


def test_bad_download_never_publishes_or_executes_installer(
    monkeypatch, managed_installer_fixture,
):
    environ, _, _, _, _ = managed_installer_fixture
    monkeypatch.setattr(
        update_installer, "_download_installer_archive", lambda name: b"altered archive",
    )
    with pytest.raises(RuntimeError, match="Downloaded update installer failed checksum"):
        update_installer._managed_installer(platform_name="win32", environ=environ)
    assert not list(Path(environ["LOCALAPPDATA"]).rglob("uv.exe"))


def test_tampered_cached_archive_is_rejected(managed_installer_fixture):
    environ, _, _, _, _ = managed_installer_fixture
    selected = Path(update_installer._managed_installer(
        platform_name="win32", environ=environ,
    ))
    archive_path = next(selected.parent.glob("*.zip"))
    archive_path.write_bytes(b"tampered archive")
    with pytest.raises(RuntimeError, match="Cached update installer archive failed checksum"):
        update_installer._managed_installer(platform_name="win32", environ=environ)


def test_tampered_cached_binary_is_rejected(managed_installer_fixture):
    environ, _, _, _, _ = managed_installer_fixture
    selected = Path(update_installer._managed_installer(
        platform_name="win32", environ=environ,
    ))
    selected.write_bytes(b"tampered executable")
    with pytest.raises(RuntimeError, match="Cached update installer failed checksum"):
        update_installer._managed_installer(platform_name="win32", environ=environ)


def test_managed_installer_must_report_the_pinned_version(
    monkeypatch, managed_installer_fixture,
):
    environ, _, _, _, _ = managed_installer_fixture
    monkeypatch.setattr(update_installer, "_installer_version", lambda *args: (0, 12, 16))
    with pytest.raises(RuntimeError, match="wrong version"):
        update_installer.resolve_update_installer(platform_name="win32", environ=environ)


def test_download_failure_propagates_before_any_installer_is_published(
    monkeypatch, managed_installer_fixture,
):
    environ, _, _, _, _ = managed_installer_fixture

    def unavailable(asset_name):
        raise OSError("network unavailable")

    monkeypatch.setattr(update_installer, "_download_installer_archive", unavailable)
    with pytest.raises(OSError, match="network unavailable"):
        update_installer._managed_installer(platform_name="win32", environ=environ)
    assert not list(Path(environ["LOCALAPPDATA"]).rglob("uv.exe"))


@pytest.mark.parametrize("stdout", ["", "uv not-a-version", "uv 0.12.17-dev"])
def test_unverifiable_version_is_rejected(monkeypatch, stdout):
    monkeypatch.setattr(
        update_installer.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout),
    )
    with pytest.raises(RuntimeError, match="Cannot verify"):
        update_installer._installer_version("uv", {})


def test_recovery_runs_existing_updater_with_managed_installer_on_child_path(
    monkeypatch, tmp_path,
):
    selected = str(tmp_path / "fixed" / "uv.exe")
    monkeypatch.setattr(update_installer, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(update_installer.shutil, "which", lambda command: "/existing/" + command)
    monkeypatch.setattr(update_installer, "resolve_update_installer", lambda **kwargs: selected)
    monkeypatch.setenv("PATH", "/original/path")
    calls = []
    monkeypatch.setattr(
        update_installer.subprocess, "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    update_installer.repair_windows_update()
    assert calls[0][0] == (["/existing/metalist", "update"],)
    assert calls[0][1]["check"] is True
    assert calls[0][1]["env"]["PATH"].startswith(
        str(Path(selected).parent) + update_installer.os.pathsep,
    )
    assert update_installer.os.environ["PATH"] == "/original/path"


def test_recovery_does_not_continue_after_installer_failure(monkeypatch):
    monkeypatch.setattr(update_installer, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(update_installer.shutil, "which", lambda command: "/existing/" + command)

    def broken_installer(**kwargs):
        raise RuntimeError("checksum failed")

    monkeypatch.setattr(update_installer, "resolve_update_installer", broken_installer)
    monkeypatch.setattr(
        update_installer.subprocess, "run",
        lambda *args, **kwargs: pytest.fail("must not run updater"),
    )
    with pytest.raises(RuntimeError, match="checksum failed"):
        update_installer.repair_windows_update()


def test_repair_archive_contains_current_production_resolver_and_launcher(tmp_path):
    archive_path = tmp_path / "repair.zip"
    build_repair_archive(archive_path)
    root = Path(__file__).resolve().parents[2]
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {
            "Repair-MetaList.cmd", "update_installer.py", "README.txt",
        }
        assert archive.read("update_installer.py") == (
            root / "app/services/update_installer.py"
        ).read_bytes()
        assert archive.read("Repair-MetaList.cmd") == (
            root / "scripts/Repair-MetaList.cmd"
        ).read_bytes()
    original_archive = archive_path.read_bytes()
    with pytest.raises(FileExistsError):
        build_repair_archive(archive_path)
    assert archive_path.read_bytes() == original_archive
