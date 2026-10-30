"""Supply-chain checks for vendored JavaScript that is built from several npm packages (Excalidraw)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("check_supply_chain", ROOT / "scripts" / "check_supply_chain.py")
assert _SPEC is not None and _SPEC.loader is not None
check_supply_chain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_supply_chain)

EXCALIDRAW_BUNDLE = "app/static/js/vendor/excalidraw-0.18.1.min.js"


def _excalidraw_entry() -> dict:
    libraries = check_supply_chain.check_vendor_files(ROOT)
    entries = [library for library in libraries if library["path"] == EXCALIDRAW_BUNDLE]
    assert len(entries) == 1
    return entries[0]


def test_excalidraw_bundle_is_declared_with_pinned_inputs() -> None:
    entry = _excalidraw_entry()
    packages = check_supply_chain.bundled_packages(ROOT, entry)
    versions = {(package["name"], package["version"]) for package in packages}
    assert ("@excalidraw/excalidraw", "0.18.1") in versions
    assert ("react", "18.3.1") in versions
    assert ("react-dom", "18.3.1") in versions


def test_excalidraw_bundle_excludes_unshipped_features_and_patched_advisories() -> None:
    packages = check_supply_chain.bundled_packages(ROOT, _excalidraw_entry())
    names = {package["name"] for package in packages}
    # The Mermaid importer (and its lodash-es/langium parser stack) is stubbed out of the bundle.
    assert "@excalidraw/mermaid-to-excalidraw" not in names
    assert "lodash-es" not in names
    nanoid_versions = {tuple(int(part) for part in package["version"].split(".")) for package in packages if package["name"] == "nanoid"}
    assert nanoid_versions == {(3, 3, 19)}


def test_excalidraw_bundle_never_loads_from_a_cdn() -> None:
    bundle = (ROOT / EXCALIDRAW_BUNDLE).read_text(encoding="utf-8")
    for host in ("esm.sh", "unpkg.com", "jsdelivr.net"):
        assert host not in bundle
    assert "window.EXCALIDRAW_ASSET_PATH" in bundle


def test_audited_versions_expand_bundles_into_their_packages() -> None:
    libraries = check_supply_chain.check_vendor_files(ROOT)
    audited = check_supply_chain.audited_versions(ROOT, libraries)
    audited_pairs = {(item["name"], item["version"]) for item in audited}
    assert ("react-dom", "18.3.1") in audited_pairs
    for library in libraries:
        # A data file (the passphrase wordlist) is no npm package: its checksum pins it.
        if "bundle" not in library and "kind" not in library:
            assert (library["name"], library["version"]) in audited_pairs


def _write_bundle_fixture(root: Path, *, locked_version: str) -> dict:
    (root / "vendor").mkdir()
    (root / "vendor" / "build.mjs").write_text("// build")
    (root / "vendor" / "package-lock.json").write_text(json.dumps({
        "packages": {
            "node_modules/example": {"version": locked_version, "integrity": "sha512-x"},
        },
    }))
    (root / "vendor" / "bundle-packages.json").write_text(json.dumps([
        {"name": "example", "version": "1.0.0", "license": "MIT", "lockKey": "node_modules/example"},
    ]))
    return {
        "name": "example",
        "version": "1.0.0",
        "bundle": {
            "build_script": "vendor/build.mjs",
            "lockfile": "vendor/package-lock.json",
            "packages": "vendor/bundle-packages.json",
        },
    }


def test_bundle_packages_must_match_the_lockfile(tmp_path: Path) -> None:
    library = _write_bundle_fixture(tmp_path, locked_version="1.0.0")
    assert check_supply_chain.bundled_packages(tmp_path, library)[0]["version"] == "1.0.0"

    drift_root = tmp_path / "drift"
    drift_root.mkdir()
    drifted = _write_bundle_fixture(drift_root, locked_version="1.0.1")
    with pytest.raises(RuntimeError, match="not pinned"):
        check_supply_chain.bundled_packages(drift_root, drifted)
