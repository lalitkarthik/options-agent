# Roadmap

Decided in a grilling session on 2026-10-14. This is the plan for the whole learning track:
what gets built, in what order, what each phase teaches, and how every ticket is worked.
If a later decision changes something here, change this file in the same PR.

## Why this exists

To get properly good at backend, infra, DevOps, system design and applied AI engineering
(agents, tools, MCP, evals, guardrails) by building, not by having Claude one-shot things.
The syllabus is Alchemyst AI's public hiring assignments
([github.com/Alchemyst-ai/hiring](https://github.com/Alchemyst-ai/hiring)); they are not
submitted. When applying to a startup like that, its current assignment is done fresh in its
own window, using the skills from here.

Goals, in order: skills and portfolio for December 2027 placements (Tower AI/ML, then SDE) and
freelance pitches; applying to AI startups. Pace: about 20 hours a week until mid-March 2027.

**Quality bar:** it works, every number is real, and Lalit can explain every line under
questioning. Not perfect. A polished repo nobody can explain (PaperLens) is the failure mode.

## The two projects

1. **options-agent** (this repo, main project). You ask an options question in plain English
   ("Is SPX 30-day implied vol rich against the last 20 days of realised vol?"). The agent calls
   tools over MCP to fetch frozen market data, computes, and answers with numbers, source and
   timestamp, or says the data is missing. An eval harness scores it against reference answers
   computed by plain Python from the same frozen data. Prior design notes:
   `D:\second-brain\placement-vault\projects\project-agentic-options-research.md`.
2. **Agent Console** (separate repo, weeks 4-5). Alchemyst's June 2026 full-stack assignment:
   a Next.js client for a provided WebSocket agent server that, in chaos mode, drops
   connections, reorders and duplicates messages and sends bad heartbeats. No LLM, no cost.
   Spec: [Alchemyst-ai/full-stack-engineer-assignment](https://github.com/Alchemyst-ai/full-stack-engineer-assignment).

## Phases

| Phase | Weeks | What gets built | Concepts learned | Assignment it covers |
|---|---|---|---|---|
| P1 Agent core | 1-3 | Options MCP server over frozen Databento snapshots; a hand-written agent loop (no framework); structured output and guardrails; eval harness v1 with ~10 then ~30 tasks; OpenTelemetry traces into Langfuse Cloud (free tier; self-hosting moves to P4) | Tool calling, MCP (stdio, then streamable HTTP), JSON schemas, context engineering, eval design (pass^k, tolerance graders, LLM judge), prompt caching, tracing | Resume Assistant (structured output, "not available", tool vs LLM), Agent |
| Agent Console | 4-5 | Separate repo, see above | WebSockets, heartbeats, sequence numbers, reorder buffer, dedupe, idempotency, reconnect with backoff and jitter, resume and replay, at-least-once delivery, TypeScript, React rendering | Full-stack AI (June 2026) |
| P2 Backend | 6-8 | FastAPI service, Postgres, auth, a job API. Jobs first on an in-process queue (feel what a restart loses), then RabbitMQ workers. Agent events into Redis Streams with sequence numbers, so a client reconnecting to any API replica resumes from its last seq. Streaming answers the user can interrupt. Docker Compose, CI | REST design, schema, indexes, transactions, migrations; work queue vs event log; acks, prefetch, retries, dead-letter queues, back-pressure, idempotency keys; rate limiting, caching, connection pools | Platform (queues, long-running jobs), B2B custom agent (streaming, interruption, idle detection) |
| P3 Reliability | 9-10 | Single agent vs multi-agent; the orchestrator rebuilt in LangGraph as one comparison variant (success, cost, lines of code); deeper guardrails; Upstox as a second data adapter; load tests; cost per task | Prompt injection through tool output, adapter pattern, daily token expiry, concurrency limits, Locust or k6, latency percentiles, cost modelling | Platform (concurrency, cost), Agent and Solutions (MCP server) |
| P4 Infra | 11-14 | Terraform on AWS: VPC, private subnets, the gateway as the only public endpoint, workers and the MCP server on private VMs talking over the subnet; then containers on Kubernetes (k3s on EC2, EKS for one day); OpenTelemetry into Grafana (Prometheus, Tempo, Loki) with alerts | Subnets, NAT, security groups, IaC, systemd, secrets, Kubernetes basics, metrics, logs, traces, alerting | DevOps (May 2026), Infra (observability) |
| P5 Self-hosted model | 15-17 | Qwen-7B on vLLM on a GPU node behind an OpenAI-compatible endpoint, run through the same eval as Claude | Inference serving, tokens per second, batching, GPU cost vs API cost | Infra (June 2025) |
| P6 Write-up | 18-20 | "What changes at 100x users and a 100x model" design doc, honest README with real eval numbers, demo; buffer | Sharding, replication, consistent hashing, CDNs, Kafka partitions: as design reasoning, since the project does not need them | DevOps writeup |

## How every ticket is worked

### At the start of each phase

1. **Research** how strong teams built each part of the phase (mattpocock `research`, primary
   sources: code, specs, papers, official docs). Output: `docs/research/<phase>-references.md`,
   with, per part, 2-3 well-built reference projects, how each does it, what we take and what we
   deliberately do not. This is how the Convex Hedge engine got its bus (NautilusTrader) and its
   event-driven design (Netflix): copy proven designs on purpose, and say so.
2. **Design grilling**, informed by the research.
3. **Write the phase docs**: `CONTEXT.md` (the vocabulary), `docs/design/<phase>.md` (problem,
   solution, decisions), one ADR per decision citing the reference it took from.
4. **Tickets** as GitHub issues, each with a "Concepts" section.

### Each ticket

Every ticket carries one label, suggested when tickets are written and Lalit's to flip:

- **`learn`**: the first time a concept appears (first MCP tool, first queue consumer, first
  Terraform module, first reconnect loop). Lalit writes it. Claude does not write its code.
- **`glue`**: repeats and plumbing (CRUD routes, UI, config). In P1 Claude builds each one as a
  PR into `main` with a walkthrough (what, file by file; why; concepts with resources; a ChatGPT
  prompt); Lalit skims and merges. From P2, feature-loop's orchestrator builds them; it skips
  `learn` tickets.

**Doubts go to ChatGPT.** Lalit's ChatGPT Go project is connected to this repo. Every walkthrough
and every `learn` ticket start comes with a ready-to-paste prompt naming the files, issue and docs
to read, so back-and-forth questions happen there and Claude usage goes to building and review.

A `learn` ticket goes:

1. **Grill** the design briefly. Each decision becomes an ADR in `docs/design/decisions/`;
   Claude drafts the context, Lalit writes the "why" paragraph in plain words.
2. **Teach**: Claude explains the concept in chat (with a diagram where it helps) and lists the
   resources in the ticket issue under a "Concepts" heading: every genuinely good video, article
   and official doc, ranked "start here" first, not a fixed one of each. Then doubts, back and
   forth. No separate notes system.
3. **Build test-first** (mattpocock `tdd`): write a failing test for the behaviour, make it
   pass, clean up.
4. **Review**: open a PR, run `/code-review high --comment` (inline comments) and mattpocock
   `code-review` (does it match the ticket). The reviewer explains the problem and the concept
   behind it and does not write the fix. A custom mentor-review skill only if this is still
   annoying after three PRs.
5. **Fix and merge** by Lalit.

## Stack and decisions

| Question | Decision |
|---|---|
| Backend language | Python (FastAPI). TypeScript through the frontend and the Agent Console |
| Agent framework | Hand-written loop in P1. LangGraph only as a P3 comparison variant |
| Queue | In-process first, then RabbitMQ as the work queue |
| Event log | Redis Streams, for replayable agent output |
| Observability | OpenTelemetry + Langfuse Cloud from P1; self-hosted Langfuse and the Grafana stack in P4 |
| Cloud | AWS ($159 credits, expiry still to check before P4) |
| Data | Databento for US options (P1); Upstox for NIFTY and SENSEX (P3) |
| Calculations | The Convex Hedge Trading Engine's own code and formulas, unchanged (permission given by the firm). Nothing is re-derived |
| Answer key | Replay the real engine over the downloaded files and record what it publishes at 15:45; RV from the engine's `realised.py` on index candles. Our own code never re-implements its quote handling |
| Snapshot time | 15:45 New York time |
| Docs | `CONTEXT.md`, `docs/design/`, ADRs in `docs/design/decisions/`, same format as delta-exchange-payoff and statement-extractor |
| Visibility | Private until P1 has real eval numbers, then public |

## Data rules

- **Raw Databento data never enters git.** Its licence does not allow redistribution and the
  repo will go public. The repo carries a fetch script; anyone replaying the eval
  uses their own key. Only derived results are published.
- **Data on disk** (`data/raw/`, ignored by git; `uv run fetch-data` downloads what is missing,
  `uv run fetch-data --verify` checks every file is there): six SPXW days
  pulled 2026-10-14 from `OPRA.PILLAR`, each with the day's `definition` and `statistics` (open
  interest) and `cbbo-1s` quotes for 15:30-15:46 ET, all expiries; 1.3 GB in all. The days:
  2026-06-02 (calmest of the year), 2025-11-20 (most volatile), 2026-03-18 (FOMC), 2026-03-20
  (quarterly expiry), 2025-11-26 (before Thanksgiving), 2026-05-04 (median day). The year of
  0DTE-only data with index candles is at
  `D:\Convex Hedge\Backtest-Engine-data-spike\Data` (no open interest, timestamps shifted 5h30).
- **Credentials** (Databento key, Upstox token, model API keys) live in environment variables,
  never in files that are committed. The Upstox token expires daily.

## Budgets

- **Model APIs:** up to $100 a month (the Anthropic key, renewed monthly; Claude Max covers
  Claude Code itself, not the app). The agent runs on Sonnet 5.5 ($2 / $10 per million tokens
  in / out), about $0.06 per answer and $8-9 per full exam of 30 questions x 5 trials, with
  prompt caching on. Opus 5.5 and Haiku 5.5 later as comparison runs.
- **AWS:** budget alarms at $25, $75 and $125, set before anything is provisioned. Bring infra
  up per working session and `terraform destroy` after. Known traps: a NAT gateway is about $32
  a month, the EKS control plane about $73 a month, and new accounts have zero GPU quota until a
  request is approved. The P5 GPU benchmark should cost about $10-20.
