# Raw market data and credentials never enter git

Status: accepted (2026-10-14)

The Databento licence does not allow redistributing raw data, and the repo will go public. API keys and the daily Upstox token are secrets.

**Decision.** Raw files live in `data/`, which git ignores; the repo carries a fetch script and a manifest of checksums. Credentials come from environment variables only.

## Considered options

- Commit small samples of raw data: rejected; still redistribution.

## Consequences

- Someone else replaying the exam needs their own Databento key and the engine.
- Derived results (exam scores, figures quoted in the README) can be published.

## Why

*Lalit writes this section, in plain words, as part of #3. Answer: what exactly may and may not be published from this repo, and why?*
