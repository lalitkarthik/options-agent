# Every question is asked as of 15:45 New York time on a frozen snapshot day

Status: accepted (2026-10-14)

An exam needs answers that never change. Live data changes every second, and a question asked twice would have two right answers.

**Decision.** Every question names a snapshot day and is answered as of 15:45 New York time on that day. P1 has six snapshot days chosen to cover different market moods (see `docs/roadmap.md`); more can be pulled at no cost.

## Considered options

- Live data: rejected; no stable answer key.
- Several times a day: rejected for P1; more answer key work for little gain.

## Consequences

- Only 15:30 to 15:46 of each day's full-chain quotes is downloaded (about 110 to 320 MB a day instead of about 21 GB).
- Questions about other times of day are unanswerable by design.

## Why

*Lalit writes this section, in plain words, as part of the spec issue, before ticket 3. Answer: why 15:45 rather than the open or the close?*
