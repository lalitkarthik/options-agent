# Every figure comes from the Convex Hedge Trading Engine's own code, unchanged

Status: accepted (2026-10-14)

The agent answers questions about forwards, implied volatility, greeks, skew, realised volatility and gamma exposure. Each of those has several published variants (which quotes count, which delta convention, how time to expiry is counted). The Convex Hedge Trading Engine already settles every one of them after its own research, and the firm has given permission to use its code.

**Decision.** Every figure in this project is produced by the engine's own code and formulas, unchanged. Nothing is re-derived or rewritten here.

## Considered options

- Re-implement the formulas from textbooks: rejected; a rewrite can drift from the engine without anyone noticing.
- Copy the engine's code and edit it: rejected for the same reason.

## Consequences

- The project depends on a local checkout of the engine to build snapshots.
- When the engine changes a formula, snapshots are rebuilt, and the exam's answer key moves with them.
- The repo can only go public with the firm's continued agreement.

## Why

*Lalit writes this section, in plain words, as part of the spec issue, before #4. Answer: why is an unchanged engine worth more here than a cleaner rewrite of your own?*
