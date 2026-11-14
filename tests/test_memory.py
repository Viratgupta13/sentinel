"""Decision memory: store, search, and per-hunk retrieval (no API calls)."""

import pytest

from sentinel.memory.retrieve import hunk_query_tokens, render_memory_block, retrieve_for_hunk
from sentinel.memory.store import MemoryStore, db_path_for
from sentinel.models import Decision, DecisionKind, Hunk


@pytest.fixture()
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db")
    s.add_decisions(
        [
            Decision(
                repo="acme/app",
                pr_number=412,
                pr_title="Remove payment retry",
                pr_url="https://github.com/acme/app/pull/412",
                kind=DecisionKind.INCIDENT,
                decision="Payment retries were removed because they caused double charges.",
                rationale="Incident INC-23: duplicate captures under gateway timeouts.",
                files=["src/app/payments/capture.py"],
                confidence=0.9,
            ),
            Decision(
                repo="acme/app",
                pr_number=200,
                pr_title="Session TTL convention",
                kind=DecisionKind.CONVENTION,
                decision="Session expiry must stay at 1 hour for compliance.",
                rationale="Auditor requirement from SOC2 review.",
                files=["src/app/auth/session.py"],
                confidence=0.8,
            ),
        ]
    )
    yield s
    s.close()


def _hunk(path: str, content: str) -> Hunk:
    return Hunk(
        hunk_id=f"{path}#0",
        file_path=path,
        header="",
        old_start=1,
        old_lines=1,
        new_start=1,
        new_lines=1,
        content=content,
    )


def test_db_path_is_per_repo(tmp_path):
    p = db_path_for(str(tmp_path), "acme/app")
    assert p.name == "acme__app.db"


def test_search_finds_by_keyword(store):
    results = store.search(["retry", "payment"])
    assert any(d.pr_number == 412 for d in results)


def test_harvested_tracking(store):
    assert not store.is_harvested(999)
    store.mark_harvested(999, 0)
    assert store.is_harvested(999)
    assert store.stats()["harvested_prs"] == 1


def test_query_tokens_skip_keywords():
    hunk = _hunk(
        "src/app/payments/capture.py",
        "@@ -1,3 +1,4 @@\n+    if should_retry(payment):\n+        capture_payment(payment)\n",
    )
    tokens = hunk_query_tokens(hunk)
    assert "payment" in tokens
    assert "if" not in tokens  # too short / stopword
    assert "payments" in tokens  # from the file path


def test_retrieve_ranks_same_file_first(store):
    hunk = _hunk(
        "src/app/payments/capture.py",
        "@@ -1 +1 @@\n+retry_policy = ExponentialBackoff()\n+capture(payment)\n",
    )
    retrieved = retrieve_for_hunk(store, hunk, top_k=2)
    assert retrieved, "expected at least one memory"
    assert retrieved[0].decision.pr_number == 412
    assert "file" in retrieved[0].matched_on


def test_render_block_cites_pr(store):
    hunk = _hunk("src/app/auth/session.py", "@@ -1 +1 @@\n+session.expires = days(30)\n")
    block = render_memory_block(retrieve_for_hunk(store, hunk, top_k=3))
    assert "PR #200" in block
    assert "1 hour" in block


def test_render_empty_is_empty():
    assert render_memory_block([]) == ""
