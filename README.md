# Sentinel

**Context-aware PR risk reviewer with tiered LLM routing.**

AI code-review tools spend the same strong model on every line of every PR - expensive,
slow, and noisy. Sentinel routes work by risk:

```
GitHub PR ──► diff parser ──► static signals (free)
                                   │
                     skip: lockfiles, generated, docs
                                   │
                        Haiku triage (cheap, batched)      ◄── every real hunk
                                   │
                         risk ≥ threshold? ──► Opus deep review (strong, cached)
                                   │
                        report: findings + per-model cost ledger
```

Three design pillars (the "gaps" this project attacks):

1. **Review quality** - deep review only where it matters; precision over noise;
   critical areas (auth/payments/db/security) get a static floor that a cheap-model
   miss can't bury.
2. **Team context** *(Phase 2)* - a decision memory mined from past PRs, review
   comments, and incidents, retrieved into the review prompt with citations.
3. **Cost** - tiered models + prompt caching + zero-cost skips, with a per-PR
   usage ledger and a naive-baseline comparison printed on every run.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env         # add ANTHROPIC_API_KEY
sentinel review https://github.com/<owner>/<repo>/pull/<n>
```

Useful flags:

```bash
sentinel review <pr-url> --out report.md --json report.json
sentinel review <pr-url> --threshold 6 --max-hunks 5   # stricter + cheaper
sentinel review --diff changes.diff                    # local diff, no GitHub
sentinel review --diff changes.diff --static-only      # zero LLM calls (free dry run)
```

Exit codes: `0` clean, `1` pipeline error, `2` high-severity findings (CI-friendly).

## Decision memory (Phase 2)

Mine a repo's merged-PR history once; every later `sentinel review` of that repo
automatically retrieves relevant past decisions (with PR citations) into the
deep-review prompt:

```bash
sentinel memory build owner/name --limit 200   # Sonnet extracts durable decisions
sentinel memory stats owner/name
sentinel memory search owner/name "payment retry timeout"
```

Memories live in `~/.sentinel/memory/<owner>__<name>.db` (SQLite + FTS5; BM25
keyword + path-overlap retrieval - deterministic and dependency-free). Most PRs
yield zero decisions by design: the memory only works if it stays high-precision.
A hunk that re-introduces something the team removed on purpose (incident/constraint)
is escalated to high severity with the source PR cited.

## Configuration

Env vars (prefix `SENTINEL_`, see `.env.example`): `TRIAGE_MODEL`, `REVIEW_MODEL`,
`RISK_THRESHOLD` (default 4), `MAX_REVIEW_HUNKS` (default 12), `TRIAGE_BATCH_SIZE`.

Models: triage `claude-haiku-5-5`, deep review `claude-opus-5-5`
(decision-memory extraction, Phase 2: `claude-sonnet-5-5`).

### Free-tier providers

`SENTINEL_PROVIDER=openai` routes every LLM call to any OpenAI-compatible
endpoint (Groq, Google AI Studio, OpenRouter - all have free tiers); see the
commented blocks in `.env.example`. Structured output is enforced by prompt +
Pydantic validation on this path; Anthropic-only features (prompt caching,
effort control, native JSON-schema constraint) are skipped, and unknown models
show $0 in the cost ledger.

## Webhook server (Phase 5)

The vision end-to-end: a PR is opened → Sentinel reviews it automatically →
the findings land as a comment on the PR, and on the live dashboard.

```bash
pip install -e ".[server]"
sentinel serve --port 8000       # POST /webhook/github · GET /dashboard · GET /healthz
```

Point a GitHub webhook at `/webhook/github` (content type `application/json`,
events: *Pull requests*) and set `SENTINEL_WEBHOOK_SECRET` to the webhook's
secret - unsigned payloads are only accepted when no secret is configured
(local testing). On `opened` / `synchronize` / `reopened` / `ready_for_review`
(drafts skipped) the server reviews the PR in the background and upserts a
single marker-tagged comment per PR (updated on each push, no comment spam;
needs a `GITHUB_TOKEN` with write access; disable with
`SENTINEL_POST_COMMENTS=false`).

`GET /dashboard` serves the same unified dashboard as `sentinel costs --html`:
recent reviews (risk + findings), decision-memory stats per repo, tokens by
model, and total spend vs the naive baseline.

## Hosted hub (Phase 6)

The same server becomes a multi-tenant product when GitHub App + OAuth env
vars are set (see [docs/HOSTING.md](docs/HOSTING.md) for the click-by-click
deploy guide - Render free tier works):

- **Sign in with GitHub** (OAuth, zero scopes) with signed session cookies
- users **install the Sentinel GitHub App** on any repos, public or private;
  `installation` webhooks keep the tenant store in sync
- every review runs with that installation's **short-lived token** - no PATs,
  and comments post as the app
- `/dashboard` is per-user (only repos your installations cover) and
  **live-updates** as new PRs are reviewed

## Development

```bash
pytest                 # unit + wiring tests (no API key needed)
ruff check src tests
docker build -t sentinel . && docker run sentinel version
```

## Roadmap

- [x] **Phase 1 - tiered review pipeline**: diff parsing, static signals,
  Haiku triage, Opus deep review, cost ledger, CLI, CI, Docker
- [x] **Phase 2 - decision memory**: Sonnet mines merged PRs + review comments
  into per-repo SQLite/FTS5 memory; risky hunks retrieve past decisions with
  PR citations into the review prompt
- [x] **Phase 3 - cost history + dashboard**: every run recorded to
  `~/.sentinel/costs.db`; `sentinel costs [--html dashboard.html]` aggregates
  spend, tokens by model, and savings vs the naive baseline (cache tuning +
  Batch API backfills pending an Anthropic-key run)
- [x] **Phase 4 - eval harness**: `sentinel eval collect/run/grade` - revert-labeled
  datasets, resumable ablation backtests (static/triage/full/memory), recall +
  noise + cost table (see `evals/README.md`); headline numbers pending a
  strong-model run
- [x] **Phase 5 - webhook server**: `sentinel serve` - GitHub `pull_request`
  webhook (HMAC-verified) triggers an automatic review and posts/updates one
  review comment per PR; live unified dashboard at `/dashboard`
- [x] **Phase 6 - hosted hub**: GitHub App + "Sign in with GitHub" - install
  on any repo, reviews run on per-installation tokens, per-user live
  dashboard; one-click Render deploy (`render.yaml`, `docs/HOSTING.md`)
  (inline per-line comments + 👍/👎 feedback loop pending)
- [x] **Phase 7a - repo-centric UI**: home is your repo grid; each repo page
  shows live open PRs (risk-badged once reviewed), open issues, review
  history and decision-memory stats; costs move to `/overview`
  (7b "ask the repo" RAG chat pending)
