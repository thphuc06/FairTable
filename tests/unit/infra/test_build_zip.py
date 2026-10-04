"""The Runtime package is built the way the AgentCore documentation asks (modes, no bytecode, size limits) and
pinned to the same versions as pyproject.toml."""

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("build_zip", ROOT / "infra" / "runtime" / "build_zip.py")
build_zip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_zip)


def tree(base: Path) -> Path:
    (base / "pkg" / "__pycache__").mkdir(parents=True)
    (base / "pkg" / "mod.py").write_text("x = 1\n")
    (base / "pkg" / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\x00")
    (base / "stray.pyc").write_bytes(b"\x00")
    (base / "entry.py").write_text("print('hi')\n")
    return base


def test_files_get_mode_644_and_directories_755_and_no_bytecode_is_included(tmp_path):
    report = build_zip.write_zip(tree(tmp_path / "s"), tmp_path / "out.zip")
    with zipfile.ZipFile(report.path) as z:
        modes = {i.filename: i.external_attr >> 16 for i in z.infolist()}
    assert modes["entry.py"] == 0o100644 and modes["pkg/mod.py"] == 0o100644
    assert modes["pkg/"] == 0o40755
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in modes)
    assert report.files == 2


def test_the_same_input_gives_the_same_bytes(tmp_path):
    staging = tree(tmp_path / "s")
    a = build_zip.write_zip(staging, tmp_path / "a.zip").path.read_bytes()
    b = build_zip.write_zip(staging, tmp_path / "b.zip").path.read_bytes()
    assert a == b


def test_entries_are_sorted(tmp_path):
    report = build_zip.write_zip(tree(tmp_path / "s"), tmp_path / "out.zip")
    with zipfile.ZipFile(report.path) as z:
        names = z.namelist()
    assert names == sorted(names)


def test_a_package_over_the_zipped_limit_is_refused_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(build_zip, "MAX_ZIPPED", 10)
    with pytest.raises(build_zip.PackageError, match="250 MB"):
        build_zip.write_zip(tree(tmp_path / "s"), tmp_path / "out.zip")
    assert not (tmp_path / "out.zip").exists()


def test_a_package_over_the_unpacked_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(build_zip, "MAX_UNZIPPED", 5)
    with pytest.raises(build_zip.PackageError, match="750 MB"):
        build_zip.write_zip(tree(tmp_path / "s"), tmp_path / "out.zip")


def test_the_limits_are_the_documented_ones():
    assert build_zip.MAX_ZIPPED == 250 * 1024 * 1024 and build_zip.MAX_UNZIPPED == 750 * 1024 * 1024


def test_the_application_is_added_without_bytecode(tmp_path):
    staging = tmp_path / "s"
    staging.mkdir()
    build_zip.add_application(staging)
    assert (staging / "runtime_entry.py").is_file() and (staging / "server" / "app.py").is_file()
    assert sorted(p.name for p in (staging / "policies").glob("*.cedar")) == sorted(
        p.name for p in (ROOT / "policies").glob("*.cedar"))
    assert (staging / "policies" / "pep1.cedarschema").is_file() and (staging / "policies" / "pep2.cedarschema").is_file()
    assert not list(staging.rglob("__pycache__")) and not list(staging.rglob("*.pyc"))
    assert (staging / "web").is_dir() and (staging / "simulator").is_dir()  # the owner console on Lambda (D-068)
    assert not (staging / "tests").exists() and not list(staging.rglob("strands"))  # but no tests and no agent framework


def test_wheels_are_unpacked_into_the_root(tmp_path):
    wheels, staging = tmp_path / "w", tmp_path / "s"
    wheels.mkdir()
    staging.mkdir()
    with zipfile.ZipFile(wheels / "demo-1.0-py3-none-any.whl", "w") as z:
        z.writestr("demo/__init__.py", "VERSION = 1\n")
        z.writestr("demo-1.0.dist-info/METADATA", "Name: demo\n")
    assert build_zip.unpack_wheels(wheels, staging) == 1
    assert (staging / "demo" / "__init__.py").is_file() and (staging / "demo-1.0.dist-info" / "METADATA").is_file()


def test_the_download_asks_for_arm64_wheels_only_and_no_dependency_resolution(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(build_zip.subprocess, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    build_zip.download_wheels(Path("r.txt"), tmp_path, "3.12")
    cmd = seen["cmd"]
    assert "--no-deps" in cmd and "--only-binary=:all:" in cmd and cmd[cmd.index("--python-version") + 1] == "3.12"
    platforms = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--platform"]
    assert platforms and all(p.endswith("_aarch64") for p in platforms)
    assert "cp312" in cmd and "abi3" in cmd


def test_the_pinned_requirements_match_pyproject():
    lines = [ln for ln in (ROOT / "infra" / "runtime" / "requirements.txt").read_text().splitlines()
             if ln and not ln.startswith("#")]
    pins = dict(ln.split("==") for ln in lines)
    assert all("==" in ln for ln in lines) and len(pins) == len(lines)  # exact and unique
    pyproject = (ROOT / "pyproject.toml").read_text()
    for name in ("fastmcp", "mcp", "cedarpy"):
        wanted = re.search(rf'"{name}==([0-9.]+)"', pyproject).group(1)
        assert pins[name] == wanted
    for name in ("fastapi", "mangum"):  # the owner console on Lambda (D-068)
        assert pins[name] == re.search(rf'"{name}==([0-9.]+)"', pyproject).group(1)
    for absent in ("strands-agents", "openai", "pytest"):
        assert absent not in pins  # the simulator's framework and the tests are not part of the package
