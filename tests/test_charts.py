"""Server-rendered charts: activity buckets, severity split, hunk funnel."""

import time

from sentinel.costs import RunRow
from sentinel.report import charts


def _row(days_ago: float, risk: int, now: float) -> RunRow:
    return RunRow(
        ts=now - days_ago * 86400, command="review", repo="a/b", pr_number=1,
        total_hunks=10, skipped_hunks=2, deep_reviewed_hunks=1, cost_usd=0.0,
        naive_cost_usd=0.0, models=[], max_risk=risk,
    )


def test_activity_buckets_by_day_and_band():
    now = time.mktime((2026, 11, 17, 12, 0, 0, 0, 0, -1))
    rows = [_row(0, 9, now), _row(0, 2, now), _row(3, 5, now), _row(30, 9, now)]
    svg = charts.activity(rows, days=14, now=now)
    assert "3 reviews in the last 14 days" in svg          # 30-day-old row is out
    assert "Nov 17 · 2 reviews (1 high risk, 1 low)" in svg
    assert "Nov 14 · 1 review (1 medium)" in svg
    assert "No reviews in this window" not in svg
    assert "No reviews in this window" in charts.activity([], now=now)


def test_severity_and_funnel():
    html = charts.severity([{"severity": "high"}, {"severity": "high"}, {"severity": "low"}])
    assert "3 total" in html and "67%" in html and "33%" in html
    f = charts.funnel(14, 3, 2)
    assert "14%" in f and "Triaged: 11 hunks" in f and "Deep reviewed: 2 hunks" in f


def test_radar_puts_riskier_prs_nearer_center():
    now = time.time()
    hot, calm = _row(0, 10, now), _row(0, 1, now)
    calm.pr_number = 2
    html = charts.radar([hot, calm], repos=3)
    assert "3 repositories" in html and "1 high-risk PR near the center" in html
    assert 'class="blip c-crit hot"' in html and 'class="blip c-good"' in html
    assert "Nothing high-risk right now" in charts.radar([calm], repos=1)
