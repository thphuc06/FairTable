"""Build the AgentCore Runtime deployment package (direct code deployment): ``dist/fairtable-runtime.zip``.

    python infra/runtime/build_zip.py [--out dist/fairtable-runtime.zip] [--python 3.12]

What Runtime needs (AWS docs "Direct code deployment for Python", checked 2026-09-30, docs/PLAN.md 3a):
* dependencies as **manylinux aarch64** wheels (Runtime runs on Graviton), unpacked at the root of the zip
  (it is mounted at /var/task, the first entry of ``sys.path``);
* no ``__pycache__`` (bytecode built elsewhere may not match);
* file mode 644 and directory mode 755 (a zip made on Windows otherwise carries no useful mode bits);
* at most 250 MB zipped and 750 MB unpacked;
* an entry point file at the root: ``runtime_entry.py`` (an MCP server on 0.0.0.0:8000/mcp, stateless).

The package holds ``server/``, ``policies/``, ``runtime_entry.py`` and the pinned dependencies in
``requirements.txt`` next to this file. The same inputs give the same bytes (fixed timestamps, sorted order).
Downloading wheels needs the internet and nothing else: no AWS account, no Docker, no ``uv``.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = Path(__file__).with_name("requirements.txt")
PLATFORMS = ("manylinux2014_aarch64", "manylinux_2_17_aarch64", "manylinux_2_28_aarch64", "manylinux_2_34_aarch64")
APP_DIRS = ("server", "policies", "workers", "web", "simulator")
APP_FILES = ("runtime_entry.py",)
SKIP_PARTS = {"__pycache__"}
SKIP_SUFFIXES = (".pyc", ".pyo")
MAX_ZIPPED = 250 * 1024 * 1024
MAX_UNZIPPED = 750 * 1024 * 1024
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # reproducible archives


@dataclass(frozen=True)
class Report:
    path: Path
    files: int
    zipped: int
    unzipped: int


class PackageError(Exception):
    """The package would not be accepted by Runtime."""


def download_wheels(requirements: Path, dest: Path, python_version: str = "3.12") -> None:
    """The pinned set as aarch64 wheels (``--no-deps``: the list is already complete)."""
    tag = python_version.replace(".", "")
    cmd = [sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--dest", str(dest),
           "--python-version", python_version, "--implementation", "cp", "--abi", f"cp{tag}", "--abi", "abi3",
           "--abi", "none", "-r", str(requirements)]
    for platform in PLATFORMS:
        cmd += ["--platform", platform]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def unpack_wheels(wheels: Path, staging: Path) -> int:
    count = 0
    for wheel in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(wheel) as z:
            z.extractall(staging)
        count += 1
    return count


def add_application(staging: Path, root: Path = ROOT) -> None:
    for name in APP_DIRS:
        shutil.copytree(root / name, staging / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
                        dirs_exist_ok=True)
    for name in APP_FILES:
        shutil.copy2(root / name, staging / name)


def _wanted(path: Path, staging: Path) -> bool:
    relative = path.relative_to(staging)
    return not (set(relative.parts) & SKIP_PARTS) and path.suffix not in SKIP_SUFFIXES


def write_zip(staging: Path, out: Path) -> Report:
    """Deterministic zip of ``staging``: sorted, fixed time, mode 644 for files and 755 for directories."""
    entries = sorted(p for p in staging.rglob("*") if _wanted(p, staging))
    unzipped = sum(p.stat().st_size for p in entries if p.is_file())
    if unzipped > MAX_UNZIPPED:
        raise PackageError(f"{unzipped} bytes unpacked is over the 750 MB limit")
    out.parent.mkdir(parents=True, exist_ok=True)
    files = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in entries:
            name = path.relative_to(staging).as_posix()
            if path.is_dir():
                info = zipfile.ZipInfo(name + "/", FIXED_TIME)
                info.external_attr = (0o40755 << 16) | 0x10
                z.writestr(info, b"")
            else:
                info = zipfile.ZipInfo(name, FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                z.writestr(info, path.read_bytes())
                files += 1
    zipped = out.stat().st_size
    if zipped > MAX_ZIPPED:
        out.unlink()
        raise PackageError(f"{zipped} bytes zipped is over the 250 MB limit")
    return Report(out, files, zipped, unzipped)


def build(out: Path, python_version: str = "3.12", requirements: Path = REQUIREMENTS) -> Report:
    with tempfile.TemporaryDirectory() as tmp:
        wheels, staging = Path(tmp, "wheels"), Path(tmp, "package")
        wheels.mkdir()
        staging.mkdir()
        download_wheels(requirements, wheels, python_version)
        unpack_wheels(wheels, staging)
        add_application(staging)
        return write_zip(staging, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "fairtable-runtime.zip")
    parser.add_argument("--python", default="3.12", help="CPython version of the Runtime (PYTHON_3_12)")
    args = parser.parse_args(argv)
    r = build(args.out, args.python)
    print(f"{r.path}: {r.files} files, {r.zipped / 1e6:.1f} MB zipped, {r.unzipped / 1e6:.1f} MB unpacked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
