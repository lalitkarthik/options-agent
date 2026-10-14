# The answer key is what the engine publishes when replayed over the downloaded files

Status: accepted (2026-10-14)

Calling the engine's calculation functions from our own script would still leave one part of the engine out: the chain engine that decides which quotes count (stale, crossed, zero bids) and which flavour to use. A script of ours could choose differently and the numbers would quietly stop matching.

**Decision.** Snapshots are built by replaying the real engine over the downloaded Databento files in its own file mode and recording what it publishes at the as-of time. Realised volatility comes from the engine's realised-volatility functions over index candles.

## Considered options

- Our own script calling the engine's functions in order: rejected; it re-implements quote selection.
- Trust the figures already stored in the Backtest-Engine data: rejected; a different pipeline. They are kept only as a cross-check.

## Consequences

- The snapshot builder needs the engine running locally, with its message bus.
- Any disagreement between the replay and the stored Backtest-Engine figures is a finding worth reporting to the firm.

## Why

*Lalit writes this section, in plain words, as part of the spec issue, before #4. Answer: what could go wrong if the answer key came from your own script instead of the engine's replay?*
