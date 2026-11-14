from pathlib import Path

from sentinel.diff.parser import parse_diff
from sentinel.models import FileStatus

FIXTURE = Path(__file__).parent / "fixtures" / "sample.diff"


def _files():
    return parse_diff(FIXTURE.read_text())


def test_file_count_and_paths():
    files = _files()
    assert [f.path for f in files] == [
        "src/app/auth/session.py",
        "src/app/utils/format.py",
        "package-lock.json",
        "README.md",
        "tests/test_format.py",
    ]


def test_hunk_splitting():
    files = {f.path: f for f in _files()}
    auth = files["src/app/auth/session.py"]
    assert len(auth.hunks) == 2
    first = auth.hunks[0]
    assert first.hunk_id == "src/app/auth/session.py#0"
    assert first.old_start == 10
    assert first.new_start == 10
    assert first.removed == 3
    assert first.added == 1
    assert "MFA required" in first.content


def test_classification_flags():
    files = {f.path: f for f in _files()}
    assert files["package-lock.json"].is_lockfile
    assert files["README.md"].is_docs
    assert files["tests/test_format.py"].is_test
    assert not files["src/app/auth/session.py"].is_test


def test_new_file_status():
    files = {f.path: f for f in _files()}
    assert files["tests/test_format.py"].status == FileStatus.ADDED
    assert files["src/app/auth/session.py"].status == FileStatus.MODIFIED


def test_empty_diff():
    assert parse_diff("") == []
