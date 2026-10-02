"""P3-7: the public repository is English only and holds no key, account id or personal address.

The files checked are the ones git would commit: tracked ones and new ones that are not ignored (`git ls-files
--cached --others --exclude-standard`). The test is skipped outside a git checkout. The development logins in the
README (`alice-dev-pass` and the like) are public on purpose and are not matched by any pattern here.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = {".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".json", ".js", ".cedar", ".cedarschema", ".drawio", ".svg",
        ".html", ".ini", ".cfg", ".sh", ".example", ""}
VIETNAMESE = re.compile(
    "[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
FAKE_ACCOUNTS = {"123456789012", "111122223333"}  # the made-up ids used by tests and examples
KEY_PATTERNS = {
    "an AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "a secret access key": re.compile(r"aws_secret_access_key\s*[=:]\s*['\"]?(?!local\b)[A-Za-z0-9/+=]{30,}"),
    "a Bearer token": re.compile(r"Bearer\s+eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[a-z]{2,}")
EMAIL_OK = re.compile(r"(@example\.|@anthropic\.com|@devpost\.com|@users\.noreply\.github\.com|noreply@)")
ACCOUNT = re.compile(r"(?<![\w.-])\d{12}(?![\w-])")


def repo_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
                             capture_output=True, check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    files = []
    for name in out.decode("utf-8").split("\0"):
        path = ROOT / name
        if name and path.is_file() and path.suffix.lower() in TEXT and path.stat().st_size < 3_000_000:
            files.append(path)
    return files


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_there_is_something_to_check():
    assert len(repo_files()) > 200


def test_no_file_holds_vietnamese_text():
    found = [str(p.relative_to(ROOT)) for p in repo_files() if p.name != "test_language_and_secrets.py"
             and VIETNAMESE.search(text_of(p))]
    assert not found, "Vietnamese text in: " + ", ".join(found)


def test_no_file_holds_a_key_or_a_token():
    found = []
    for path in repo_files():
        text = text_of(path)
        for what, pattern in KEY_PATTERNS.items():
            if pattern.search(text):
                found.append(f"{path.relative_to(ROOT)}: {what}")
    assert not found, found


def test_no_file_names_a_real_account_id_or_a_personal_address():
    found = []
    for path in repo_files():
        if path.suffix == ".json" and path.parent.name == "reports":
            continue  # measured trials: numbers, no accounts
        text = text_of(path)
        found += [f"{path.relative_to(ROOT)}: account id {m}" for m in ACCOUNT.findall(text) if m not in FAKE_ACCOUNTS
                  and not re.fullmatch(r"1[0-9]{11}", m)]  # epoch milliseconds start with 1 and have 13 digits; belt and braces
        found += [f"{path.relative_to(ROOT)}: address {m}" for m in EMAIL.findall(text) if not EMAIL_OK.search(m)]
    assert not found, found


def test_the_environment_file_is_never_committed():
    tracked = subprocess.run(["git", "ls-files", ".env", ".env.local"], cwd=ROOT, capture_output=True,
                             timeout=30).stdout.decode()
    assert tracked.strip() == ""
    assert (ROOT / ".env.example").exists()
