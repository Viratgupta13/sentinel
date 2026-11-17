"""Deep review: surrounding-code context and the skeptic verification pass."""

from sentinel.config import Settings
from sentinel.llm import SentinelLLMError
from sentinel.models import Finding, Hunk, HunkReview
from sentinel.review.reviewer import _VerifyOut, surrounding_code, verify_findings

HUNK = Hunk(
    hunk_id="a.py#0", file_path="a.py", header="", old_start=5, old_lines=1,
    new_start=5, new_lines=2, added=1, removed=0, content="@@ -5,1 +5,2 @@\n x\n+y",
)
FILE = "\n".join(f"line{n}" for n in range(1, 21))
SYSTEM = [{"type": "text", "text": "reviewer role"}, {"type": "text", "text": "pr ctx"}]


def test_surrounding_code_windows_and_numbers():
    out = surrounding_code(HUNK, FILE, lines=2, max_chars=10_000)
    assert out.splitlines()[0] == "    3| line3"
    assert out.splitlines()[-1] == "    8| line8"
    assert surrounding_code(HUNK, FILE, lines=0, max_chars=10_000) == ""
    assert len(surrounding_code(HUNK, FILE, lines=50, max_chars=30)) == 30


class FakeLLM:
    def __init__(self, out=None, error=None):
        self.out, self.error, self.calls = out, error, []

    def structured(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.out


def _review():
    def f(title, sev):
        return Finding(severity=sev, title=title, detail="d", confidence=0.9)

    return HunkReview(hunk_id="a.py#0", file_path="a.py", risk_score=9, findings=[
        f("Real bug", "high"), f("Guess about unseen code", "high"), f("Maybe", "high"),
    ])


def _verdicts(*kinds):
    return _VerifyOut.model_validate({"verdicts": [
        {"index": i, "verdict": k, "reason": "r"} for i, k in enumerate(kinds)
    ]})


def test_verify_drops_refuted_keeps_uncertain_and_caps_risk():
    llm = FakeLLM(_verdicts("refuted", "refuted", "uncertain"))
    got = verify_findings(llm, Settings(_env_file=None), SYSTEM, "ctx", _review())
    assert [(f.title, f.severity) for f in got.findings] == [("Maybe", "high")]
    assert got.risk_score == 9

    medium = _review().model_copy(update={"findings": [
        _review().findings[0].model_copy(update={"severity": "medium"}),
        _review().findings[1],
    ]})
    got = verify_findings(FakeLLM(_verdicts("confirmed", "refuted")),
                          Settings(_env_file=None), SYSTEM, "ctx", medium)
    assert got.risk_score == 6  # only a medium survives: it cannot carry a 9
    sent = [b["text"] for b in llm.calls[0]["system"]]
    assert sent[1] == "pr ctx" and "reviewer role" not in sent  # skeptic role, same PR


def test_verify_keeps_confirmed_and_survives_failures():
    settings = Settings(_env_file=None)
    review = _review()
    confirmed = FakeLLM(_verdicts("confirmed", "confirmed", "confirmed"))
    assert verify_findings(confirmed, settings, SYSTEM, "c", review) == review
    broken = FakeLLM(error=SentinelLLMError("rate limited"))
    kept = verify_findings(broken, settings, SYSTEM, "c", review)
    assert kept.findings == review.findings and kept.failed
    empty = HunkReview(hunk_id="a", file_path="a", risk_score=2)
    assert verify_findings(FakeLLM(), settings, SYSTEM, "c", empty) == empty
