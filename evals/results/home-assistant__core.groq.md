# Sentinel ablation - home-assistant/core

Flag rule: max risk >= 7 or any high-severity finding.
Regressive = merged PR later reverted (conservative labels; recall is a lower bound).

| config | regressive flagged (recall) | clean flagged (noise) | avg cost/PR | avg tokens/PR |
|---|---|---|---|---|
| static | 0% (25 PRs) | 0% (15 PRs) | $0.0000 | 0 |
| triage | 24% (25 PRs) | 50% (10 PRs) | $0.0000 | 3,351 |
| full | 48% (25 PRs) | 70% (10 PRs) | $0.0000 | 5,814 |
