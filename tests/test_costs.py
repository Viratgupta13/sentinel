"""Phase 3: cost history store + dashboard rendering (no API calls)."""

from sentinel.costs import CostHistory, costs_db_path
from sentinel.models import CostLine, Finding, HunkReview, PRInfo, ReviewReport
from sentinel.report.dashboard import render_dashboard


def _report(cost: float, naive: float) -> ReviewReport:
    return ReviewReport(
        pr=PRInfo(owner="acme", repo="app", number=7, title="t", url="u"),
        total_hunks=5, skipped_hunks=1, triaged_hunks=4, deep_reviewed_hunks=2,
        verdicts=[], reviews=[],
        cost_lines=[
            CostLine(model="m-small", calls=1, input_tokens=1000, output_tokens=100,
                     cache_read_tokens=0, cache_write_tokens=0, cost_usd=cost / 2),
            CostLine(model="m-big", calls=1, input_tokens=2000, output_tokens=500,
                     cache_read_tokens=0, cache_write_tokens=0, cost_usd=cost / 2),
        ],
        total_cost_usd=cost, naive_cost_estimate_usd=naive,
    )


def test_record_and_summary(tmp_path):
    history = CostHistory(costs_db_path(str(tmp_path)))
    history.record_report(_report(0.02, 0.10))
    history.record_report(_report(0.04, 0.20))
    history.record_harvest("acme/app", 0.01, [
        {"model": "m-big", "calls": 3, "in": 500, "out": 50, "cache_read": 0, "usd": 0.01},
    ])

    rows = history.rows()
    assert len(rows) == 3
    assert rows[0].command == "memory-build"

    s = history.summary()
    assert s["runs"] == 3
    assert abs(s["total_usd"] - 0.07) < 1e-9
    assert abs(s["naive_usd"] - 0.30) < 1e-9
    assert s["by_model"]["m-big"]["calls"] == 5
    history.close()


def test_dashboard_renders(tmp_path):
    history = CostHistory(costs_db_path(str(tmp_path)))
    history.record_report(_report(0.02, 0.10))
    html = render_dashboard(history.rows(), history.summary())
    history.close()
    assert "<!doctype html>" in html
    assert "acme/app#7" in html
    assert "m-big" in html
    assert "saved vs naive" in html


def test_findings_recorded_and_rendered(tmp_path):
    report = _report(0.02, 0.10)
    report.reviews = [
        HunkReview(
            hunk_id="a.py#0", file_path="a.py", risk_score=8,
            findings=[
                Finding(severity="low", title="nit", detail="d"),
                Finding(severity="high", title="SQL injection in query", detail="d"),
            ],
        )
    ]
    history = CostHistory(costs_db_path(str(tmp_path)))
    history.record_report(report)
    row = history.rows()[0]
    history.close()

    assert row.max_risk == 8
    assert [f["severity"] for f in row.findings] == ["high", "low"]  # sorted by severity

    html = render_dashboard([row], {"runs": 1, "total_usd": 0.02, "naive_usd": 0.10,
                                    "by_model": {}})
    assert "SQL injection in query" in html
    assert "risk 8/10" in html


def test_dashboard_memory_section(tmp_path):
    history = CostHistory(costs_db_path(str(tmp_path)))
    history.record_report(_report(0.02, 0.10))
    html = render_dashboard(
        history.rows(), history.summary(),
        memory=[{"repo": "acme/app", "decisions": 6, "harvested_prs": 10,
                 "by_kind": {"constraint": 4, "incident": 2}}],
    )
    history.close()
    assert "Decision memory" in html
    assert "constraint 4" in html


def test_dashboard_empty():
    html = render_dashboard([], {"runs": 0, "total_usd": 0, "naive_usd": 0, "by_model": {}})
    assert "No runs yet" in html
