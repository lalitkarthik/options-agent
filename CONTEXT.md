# CONTEXT

**What this page contains.** The project's vocabulary: one line per term. Issues, tests, docs and
tool descriptions use these words exactly as defined here.

**How to read it.** Grouped by area. A term marked *(draft)* is settled in the ticket named after
it.

## Market data

- **SPXW** — the S&P 500 index options that expire every trading day; the only underlying in P1.
- **Chain** — every option contract of one underlying on one day: all expiries, all strikes, a call and a put at each.
- **Expiry** — the date an option contract expires; one day's chain has about 40.
- **0DTE** — the expiry that falls on the same day the question is asked about ("zero days to expiry").
- **Strike** — the index level at which an option pays out; each expiry has a ladder of them.
- **Quote** — a contract's best bid and best ask at a moment, from Databento's `cbbo-1s` feed.
- **Open interest** — how many contracts of an option are currently held, published once a day before the open; Databento's `statistics` feed.
- **Snapshot day** — a trading day whose data has been downloaded and frozen; P1 has six, listed in `docs/roadmap.md`.
- **Raw file** — one Databento download for a snapshot day (`definition`, `statistics` or `cbbo-1s`), kept in `data/raw/` and never in git.
- **As-of time** — the moment every question is about: 15:45 New York time on a snapshot day.
- **Snapshot** — the engine's figures for one snapshot day at the as-of time, built once by engine replay and never changed; `snapshots/<day>.json`, built by `scripts/build_snapshots.py`.

## The engine and its figures

- **Engine** — the Convex Hedge Trading Engine; its code and formulas are the only source of every figure.
- **Engine replay** — running the engine offline over downloaded Databento files and recording what it publishes.
- **Flavour** — which price the engine works from for a contract (for example the mid of bid and ask, or the last trade), as the engine defines it.
- **Forward** — the index level the options of one expiry imply, fitted by the engine from put and call prices.
- **Implied volatility (IV)** — the volatility that makes the Black-76 price match an option's market price; a yearly figure.
- **ATM IV** — the implied volatility at the forward, for one expiry.
- **Skew figures** — one expiry's implied volatility read at fixed points: at the forward, at the 25-delta put and call, at the 10-delta put, and the slopes between them.
- **25-delta put / call** — the strike whose forward delta is 25% (put) or 25% (call), where skew is read.
- **Risk reversal** — 25-delta call IV minus 25-delta put IV; negative when puts are dearer. The engine's `Skew.risk_reversal` (its decision 0081).
- **Realised volatility (RV)** — how much the index actually moved, from its one-minute candles, made yearly; since the open, or close-to-close over 20 sessions.
- **Implied-realised gap** — implied volatility minus realised volatility, as the engine computes it.
- **Implied move** — the index move the at-the-money straddle prices in, for one expiry.
- **Gamma exposure** — how much market makers would buy or sell for a 1% index move, from each option's gamma and open interest.
- **Gamma flip** — the index level where total gamma exposure crosses zero, nearest the current level.
- **Walls** — the strikes with the largest positive (resistance, call wall) and most negative (support, put wall) gamma exposure.
- **Vol points** — a difference between two volatilities, in percentage points (18.4% minus 14.2% is 4.2 vol points).

## The agent

- **MCP server** — the program that offers the tools to the agent over the Model Context Protocol.
- **Tool** — one function the agent can call, such as `get_skew`; returns figures with their provenance.
- **Figure** — one number a tool returns, with its unit and figure id.
- **Figure id** — a short readable name a tool gives each figure, `<tool group>:<date>:<expiry, scope or kind>:<name>`, such as `skew:2026-03-18:2026-04-17:put_25_iv` or `gamma:2026-03-18:all:flip` (chain figures add the strike: `chain:<date>:<expiry>:<strike>:<name>`); the answer cites it. The names are listed per tool in `docs/design/tool-contracts.md`.
- **Provenance** — where a figure came from: snapshot, as-of time, engine version.
- **Agent loop** — the code that sends the conversation to the model, runs the tools it asks for, sends results back, and repeats until it stops.
- **Turn** — one model call in the agent loop, with the tool calls it asked for.
- **Budget** — the agent loop's hard limits per question: turns, tokens and cost.
- **Nudge** — the short "continue" message the agent loop sends when the model stops without submitting.
- **Submission** — the agent's final answer, delivered by calling the `submit_answer` tool.
- **Answer form** — the shape of a submission, given as the `submit_answer` tool's input under a strict schema: `status`, `answer` (prose), `numbers` (each with name, value, unit and figure id) and `missing_data`, every field required.
- **Sources** — the provenance of the figures a submission cites, filled in by the agent loop from their figure ids, not written by the model.
- **Status** — `answered` or `cannot_answer`.
- **Unit** — one of a fixed list naming what a number measures: `decimal_vol` (a volatility as a yearly decimal, 0.2415 is 24.15%), `vol_points` (a difference between volatilities, in percentage points), `index_points` (an index level, strike, index move or option price), `ratio` (a delta), `per_index_point` (gamma: change in delta per index point), `index_points_per_vol_point` (vega), `usd_per_1pct_move` (gamma exposure).
- **Guardrail** — a check the agent loop runs on a submission before accepting it, such as "every number matches a figure a tool returned".
- **No submission** — the outcome when the model stops without submitting after its nudges or runs out of budget.

## The exam

- **Exam** — the fixed set of questions the agent is scored on, run in Inspect AI.
- **Question** — one exam item: the question text, its snapshot day, and its answer key entry. Inspect calls it a sample.
- **Unanswerable question** — a question whose correct answer is `cannot_answer`.
- **Answer key** — the correct figures for each question, read from the snapshots.
- **Grader** — the code that marks a submission correct, incorrect or not attempted against the answer key.
- **Tolerance** — how far a submitted number may sit from the answer key and still count as correct, set per figure.
- **Trial** — one run of one question; each question runs five trials.
- **pass^k** — the share of questions answered correctly on every one of k trials; measures reliability.
- **Net score** — +1 per correct answer, 0 per `cannot_answer` or not attempted, −3 per incorrect answer, across all trials.
- **Held-out questions** — exam questions never used while tuning prompts or tools, kept to check the score is not overfitted.
