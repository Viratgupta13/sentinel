# Sentinel noise-reduction ablation - home-assistant/core (Gemini flash-lite)

Same 40 PRs as the Groq table (25 later reverted, 15 clean), both configs run on
the same models: triage `gemini-3.1-flash-lite`, review `gemini-3.5-flash-lite`
(free tier), `MAX_HUNK_CHARS=1500`, `MAX_REVIEW_HUNKS=2`.

- **full**: the original pipeline (deep review sees the hunk only).
- **verified**: full + 40 lines of surrounding code + a skeptic pass that drops
  findings the code refutes and caps hunk risk at what surviving findings support.

Rule A (original): flagged if max(triage risk, review risk) >= 7 or any high finding.
Rule B: a deep-reviewed hunk is judged by its review risk instead of its triage risk.

| config | rule | reverted PRs flagged (recall) | clean PRs flagged (noise) | tokens/PR |
|---|---|---|---|---|
| full | A | 20% (5/25) | 13% (2/15) | 9,495 |
| verified | A | 20% (5/25) | 13% (2/15) | 10,544 |
| full | B | 16% (4/25) | 7% (1/15) | 9,495 |
| verified | B | 16% (4/25) | 7% (1/15) | 10,544 |

Findings per PR (deep review): full 0.2 on reverted / 0.0 on clean; verified
0.12 / 0.0. Only 4 of 40 PRs got any deep-review finding under full, so the
skeptic pass had almost nothing to trim.

**Reading:** with these models the reviewer is already very quiet - low noise,
but recall falls to 20% (Groq gpt-oss-120b: 48% recall, 70% noise). On this
model the context + skeptic pass changed no flag decisions and cost ~11% more
tokens. The model choice moves the recall/noise trade-off far more than the
pipeline change did; the skeptic still needs a run on a noisier reviewer model
to show whether it cuts noise without losing recall.
