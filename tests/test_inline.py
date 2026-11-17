"""Inline PR comments + 👍/👎 feedback: anchoring, dedupe, storage, pages."""

from sentinel.config import Settings
from sentinel.feedback import FeedbackStore, reaction_counts, summarize_feedback
from sentinel.models import Finding, Hunk, HunkReview, PRInfo, ReviewReport
from sentinel.report.pages import render_home, render_repo_page
from sentinel.review.inline import (
    anchor_line,
    build_inline_comments,
    comment_body,
    finding_key,
    new_side_lines,
    parse_marker,
)
from sentinel.review.reviewer import _REVIEW_SCHEMA, numbered_hunk
from sentinel.server import _post_inline

HUNK = Hunk(
    hunk_id="app/db.py#0", file_path="app/db.py", header="", old_start=10, old_lines=3,
    new_start=10, new_lines=4, added=2, removed=1,
    content="@@ -10,3 +10,4 @@\n ctx = 1\n-old = 2\n+q = f'SELECT {x}'\n+run(q)\n tail = 3",
)
REMOVED_ONLY = Hunk(
    hunk_id="gone.py#0", file_path="gone.py", header="", old_start=1, old_lines=1,
    new_start=0, new_lines=0, added=0, removed=1, content="@@ -1 +0,0 @@\n-bye",
)


def _finding(title="SQL injection", sev="high", line=None, conf=0.9):
    return Finding(severity=sev, title=title, detail="d", suggestion="use params",
                   confidence=conf, line=line)


def _report(*reviews):
    return ReviewReport(
        pr=PRInfo(owner="acme", repo="app", number=7, head_sha="abc123"),
        total_hunks=2, skipped_hunks=0, triaged_hunks=2, deep_reviewed_hunks=len(reviews),
        verdicts=[], reviews=list(reviews), cost_lines=[], total_cost_usd=0.0,
        naive_cost_estimate_usd=0.0,
    )


def test_new_side_lines_and_numbering():
    added, right = new_side_lines(HUNK)
    assert added == [11, 12]
    assert right == [10, 11, 12, 13]
    text = numbered_hunk(HUNK)
    assert "   11| +q = f'SELECT {x}'" in text
    assert "     | -old = 2" in text


def test_anchor_prefers_named_line_then_first_added():
    assert anchor_line(HUNK, 12) == 12
    assert anchor_line(HUNK, 13) == 13  # context lines are commentable too
    assert anchor_line(HUNK, 99) == 11  # outside the hunk -> first added line
    assert anchor_line(HUNK, None) == 11
    assert anchor_line(REMOVED_ONLY, None) is None


def test_build_inline_comments_orders_dedupes_and_skips():
    report = _report(
        HunkReview(hunk_id=HUNK.hunk_id, file_path=HUNK.file_path, risk_score=9, findings=[
            _finding("Minor naming", "low", conf=0.4),
            _finding("SQL injection", "high", line=12),
            _finding("sql   INJECTION", "high"),  # same key after normalizing
        ]),
        HunkReview(hunk_id=REMOVED_ONLY.hunk_id, file_path="gone.py", risk_score=5,
                   findings=[_finding("Removed guard", "medium")]),
    )
    hunks = {HUNK.hunk_id: HUNK, REMOVED_ONLY.hunk_id: REMOVED_ONLY}
    out = build_inline_comments(report, hunks)
    assert [c["title"] for c in out] == ["SQL injection", "Minor naming"]
    assert out[0]["line"] == 12 and out[0]["path"] == "app/db.py"
    assert parse_marker(out[0]["body"]) == finding_key("app/db.py", "SQL injection")
    assert build_inline_comments(report, hunks, cap=1)[0]["severity"] == "high"


def test_comment_body_asks_for_reaction():
    body = comment_body(_finding(), "0123456789ab")
    assert body.startswith("🔴 **HIGH · SQL injection**")
    assert "👍" in body and "👎" in body
    assert parse_marker(body) == "0123456789ab"
    assert parse_marker("no marker here") is None


def test_review_schema_requires_line():
    item = _REVIEW_SCHEMA["properties"]["findings"]["items"]
    assert "line" in item["required"]
    assert item["properties"]["line"]["type"] == ["integer", "null"]


def test_feedback_store_roundtrip(tmp_path):
    store = FeedbackStore(tmp_path / "costs.db")
    try:
        posted = [
            {"id": 1, "html_url": "u1", "path": "a.py", "line": 3, "key": "k1",
             "severity": "high", "title": "A"},
            {"id": 2, "html_url": "u2", "path": "b.py", "line": 4, "key": "k2",
             "severity": "low", "title": "B"},
        ]
        store.record_posted("acme/app", 7, posted)
        store.record_posted("acme/app", 7, posted)  # idempotent
        assert store.keys_for_pr("acme/app", 7) == {"k1", "k2"}
        assert store.prs_for_repo("acme/app") == [7]
        store.update_reactions({1: (2, 0), 2: (0, 1)})
        rows = store.rows({"acme/app"})
        assert len(rows) == 2
        assert store.rows({"other/repo"}) == []
    finally:
        store.close()
    fb = summarize_feedback(rows)
    assert fb == {"posted": 2, "rated": 2, "useful": 1, "not_useful": 1, "useful_pct": 50}
    assert summarize_feedback([])["useful_pct"] is None


def test_reaction_counts_reads_github_shape():
    comments = [{"id": 5, "reactions": {"+1": 3, "-1": 1, "heart": 2}}, {"id": 6}]
    assert reaction_counts(comments) == {5: (3, 1), 6: (0, 0)}


class FakeGH:
    def __init__(self, existing):
        self.existing = existing
        self.posted = []

    def list_pr_review_comments(self, owner, repo, number):
        return self.existing

    def post_inline_review(self, owner, repo, number, sha, comments, body=""):
        assert sha == "abc123"
        self.posted.extend(comments)
        return [{"id": 100 + i, "html_url": f"h{i}", "path": c["path"], "line": c["line"],
                 "body": c["body"]} for i, c in enumerate(comments)]


def test_post_inline_skips_findings_already_on_the_pr(tmp_path):
    settings = Settings(memory_home=str(tmp_path), _env_file=None)
    report = _report(HunkReview(
        hunk_id=HUNK.hunk_id, file_path=HUNK.file_path, risk_score=9,
        findings=[_finding("SQL injection", line=11), _finding("Leaks query", "medium", line=12)],
    ))
    files = [type("F", (), {"hunks": [HUNK]})()]
    old = comment_body(_finding("SQL injection"), finding_key("app/db.py", "SQL injection"))
    gh = FakeGH([{"id": 9, "body": old, "path": "app/db.py", "line": 11,
                  "reactions": {"+1": 1, "-1": 0}}])

    assert _post_inline(gh, report.pr, report, files, settings) == 1
    assert [c["title"] for c in gh.posted] == ["Leaks query"]

    store = FeedbackStore(tmp_path / "costs.db")
    try:
        rows = {r["comment_id"]: r for r in store.rows()}
    finally:
        store.close()
    assert rows[9]["up"] == 1 and rows[9]["title"] == "SQL injection"  # re-adopted
    assert rows[9]["severity"] == "high"
    assert rows[100]["title"] == "Leaks query" and rows[100]["severity"] == "medium"

    gh.posted.clear()
    gh.existing = [{"id": 100, "body": gh_body, "reactions": {}} for gh_body in
                   [comment_body(_finding("Leaks query", "medium"),
                                 finding_key("app/db.py", "Leaks query"))]] + gh.existing
    assert _post_inline(gh, report.pr, report, files, settings) == 0  # nothing new

    # A re-review that words the same finding differently, on a line Sentinel
    # already commented on, is not posted again.
    reworded = _report(HunkReview(
        hunk_id=HUNK.hunk_id, file_path=HUNK.file_path, risk_score=9,
        findings=[_finding("Unsafe string-built SQL", line=11)],
    ))
    assert _post_inline(gh, reworded.pr, reworded, files, settings) == 0


def test_pages_show_feedback():
    rows = [{"comment_id": 1, "repo": "acme/app", "pr_number": 7, "severity": "high",
             "title": "SQL injection", "path": "a.py", "line": 3, "url": "https://x/1",
             "up": 2, "down": 0, "created_ts": 0.0}]
    page = render_repo_page("acme/app", [], [], [], None, None, feedback=rows)
    assert "Reviewer feedback" in page and "Useful rate" in page and "100%" in page
    empty = render_repo_page("acme/app", [], [], [], None, None)
    assert "Reviewer feedback" in empty and "Useful rate" not in empty

    cards = [{"repo": "acme/app", "reviews": 1, "last_ts": 0, "last_risk": 9,
              "decisions": 0}]
    home = render_home(cards, None, feedback=summarize_feedback(rows))
    assert "100% of rated findings useful (1 rated)" in home
    assert "rated findings useful" not in render_home(cards, None)
