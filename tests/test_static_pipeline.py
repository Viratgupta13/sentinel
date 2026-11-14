"""End-to-end wiring test: local diff -> report, zero model calls."""

from pathlib import Path

from sentinel.config import Settings
from sentinel.pipeline import load_local_diff, review_pr

FIXTURE = Path(__file__).parent / "fixtures" / "sample.diff"


def test_static_only_report():
    pr, files = load_local_diff(str(FIXTURE))
    settings = Settings(_env_file=None)
    report = review_pr(pr, files, settings, static_only=True)

    assert report.total_hunks == 6
    assert report.skipped_hunks == 2  # lockfile + docs
    assert report.triaged_hunks == 4
    assert report.deep_reviewed_hunks == 0  # static-only never calls the review model
    assert report.total_cost_usd == 0.0

    escalated = {v.hunk_id for v in report.verdicts if v.needs_deep_review}
    # Both auth hunks must be escalated by the static prior alone.
    assert "src/app/auth/session.py#0" in escalated
    assert "src/app/auth/session.py#1" in escalated
    # Docs/lockfile must never be escalated.
    assert "README.md#0" not in escalated
    assert "package-lock.json#0" not in escalated
