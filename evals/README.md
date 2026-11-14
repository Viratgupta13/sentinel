# Sentinel evals (Phase 4)

The headline evaluation is **time-travel backtesting** on open-source repos:

1. Pick 2-3 active OSS repos (e.g. FastAPI-sized Python projects).
2. Collect historical merged PRs and label the "bad" ones: a PR is *regressive*
   if a later commit reverts it or a bug-fix commit references it
   (`Fixes #`, `Reverts #`, revert commit message patterns).
3. Run Sentinel on each historical PR **as of its merge date** (memory built only
   from history before that date - no leakage).
4. Metrics:
   - **Recall@high-risk** - fraction of regressive PRs Sentinel flagged high-risk.
   - **Precision of findings** - sampled human grading of comments (actionable or noise?).
   - **Cost per PR** - from the usage ledger, vs the naive Opus-on-everything baseline.
   - **Ablations** - static-only vs +triage vs +deep review vs +memory (Phase 2).

## Harness (built - `src/sentinel/evals/`)

```bash
sentinel eval collect owner/repo --scan 400 --clean 30   # revert-labeled dataset
sentinel eval run evals/datasets/<repo>.jsonl --configs static,triage,full
sentinel eval grade evals/datasets/<repo>.results.jsonl --hi 7 --out evals/results/<repo>.md
```

- **Labels**: a PR is *regressive* when a later merged PR reverts it (found via
  repo-wide search; body `Reverts owner/repo#N`, then title fallbacks). This is
  conservative - commit-level reverts and bug-fix follow-ups are missed - so
  recall numbers are honest lower bounds.
- **Resumable**: `eval run` appends to the results JSONL and skips (PR, config)
  pairs already present - free-tier rate limits can finish a run across
  several invocations. `--sleep N` paces LLM calls.
- **Time travel**: the `memory` config takes `--memory-db` built with
  `sentinel memory build <repo> --before <earliest merged_at in the dataset>`,
  so no post-dataset knowledge leaks into retrieval.
- **Free-tier tip (Groq 8k TPM)**: shrink requests with
  `SENTINEL_TRIAGE_BATCH_SIZE=3 SENTINEL_MAX_HUNK_CHARS=1500 SENTINEL_MAX_REVIEW_HUNKS=2`
  and `--sleep 25`. Headline numbers should be produced with the Anthropic
  models (the triage/review quality being measured is theirs).

Layout: `datasets/` (gitignored PR snapshots + results), `results/` (committed
ablation tables).
