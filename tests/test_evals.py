"""Phase 4 evals: revert labeling, metrics math, result parsing (no network)."""

from pathlib import Path

from sentinel.evals.backtest import EvalResult, load_results
from sentinel.evals.collect import collect_dataset, load_dataset, save_dataset
from sentinel.evals.grade import compute_metrics, flagged


class _FakeGH:
    """Stands in for GitHubClient in collect_dataset."""

    def __init__(self, prs):
        self._prs = prs

    def list_merged_prs(self, owner, repo, limit):
        return self._prs[:limit]

    def search_merged_prs(self, owner, repo, query, limit):
        return [pr for pr in self._prs if pr["title"].startswith("Revert")][:limit]

    def fetch_pr_json(self, owner, repo, number):
        raise RuntimeError("not in window")


def _pr(number, title, body="", merged_at="2026-01-01T00:00:00Z"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "merged_at": merged_at,
        "html_url": f"https://github.com/acme/app/pull/{number}",
    }


def test_collect_labels_reverted_pr(tmp_path):
    prs = [
        _pr(103, 'Revert "Add payment retry"', body="Reverts acme/app#101"),
        _pr(102, "Unrelated feature"),
        _pr(101, "Add payment retry"),
    ]
    rows = collect_dataset("acme/app", _FakeGH(prs), scan=10, clean=5)
    by_num = {r.number: r for r in rows}
    assert by_num[101].label == "regressive"
    assert "reverted by #103" in by_num[101].labeled_by
    assert by_num[102].label == "clean"
    assert 103 not in by_num  # the revert PR itself is neither class

    path = tmp_path / "ds.jsonl"
    save_dataset(rows, path)
    assert [r.number for r in load_dataset(path)] == [r.number for r in rows]


def test_collect_skips_unfetchable_revert_target():
    prs = [_pr(50, 'Revert "Old change"', body="Reverts acme/app#7")]
    rows = collect_dataset("acme/app", _FakeGH(prs), scan=10, clean=5)
    assert all(r.number != 7 for r in rows)  # fetch failed -> skipped, not crashed


def _result(number, label, config, max_risk=0, review_risk=0, n_high=0, cost=0.0):
    return EvalResult(
        repo="acme/app", number=number, label=label, config=config,
        max_risk=max_risk, max_review_risk=review_risk, n_findings=n_high,
        n_high=n_high, llm_triaged=1, total_hunks=2, cost_usd=cost,
        tokens=1000, naive_cost_usd=0.05,
    )


def test_flagged_rule():
    assert flagged(_result(1, "clean", "full", max_risk=7), hi_threshold=7)
    assert flagged(_result(1, "clean", "full", review_risk=8), hi_threshold=7)
    assert flagged(_result(1, "clean", "full", n_high=1), hi_threshold=7)
    assert not flagged(_result(1, "clean", "full", max_risk=6), hi_threshold=7)


def test_metrics_recall_and_noise(tmp_path):
    results = [
        _result(1, "regressive", "full", max_risk=8, cost=0.02),   # caught
        _result(2, "regressive", "full", max_risk=3, cost=0.01),   # missed
        _result(3, "clean", "full", max_risk=2, cost=0.01),        # quiet
        _result(4, "clean", "full", n_high=1, cost=0.02),          # noisy
    ]
    (m,) = compute_metrics(results, hi_threshold=7)
    assert m.config == "full"
    assert m.recall == 0.5
    assert m.clean_flag_rate == 0.5
    assert abs(m.avg_cost_usd - 0.015) < 1e-9

    path = tmp_path / "res.jsonl"
    path.write_text("".join(r.model_dump_json() + "\n" for r in results))
    assert len(load_results(Path(path))) == 4
