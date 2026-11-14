from pathlib import Path

from sentinel.diff.parser import parse_diff
from sentinel.models import RiskArea
from sentinel.signals.static import compute_signals

FIXTURE = Path(__file__).parent / "fixtures" / "sample.diff"


def _signals():
    files = parse_diff(FIXTURE.read_text())
    return {s.hunk_id: s for s in compute_signals(files)}


def test_auth_area_detected():
    signals = _signals()
    sig = signals["src/app/auth/session.py#0"]
    assert sig.area == RiskArea.AUTH
    assert sig.prior_score >= 4.0  # critical area never starts low
    assert sig.skip_reason is None


def test_skip_rules():
    signals = _signals()
    assert signals["package-lock.json#0"].skip_reason == "lockfile"
    assert signals["README.md#0"].skip_reason == "docs-only"


def test_test_file_low_prior():
    signals = _signals()
    sig = signals["tests/test_format.py#0"]
    assert sig.area == RiskArea.TESTS
    assert sig.prior_score < 4.0


def test_auth_outranks_util():
    signals = _signals()
    assert (
        signals["src/app/auth/session.py#0"].prior_score
        > signals["src/app/utils/format.py#0"].prior_score
    )
