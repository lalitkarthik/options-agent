# The exam runs in Inspect AI with our own tolerance grader

Status: accepted (2026-10-14)

Inspect already runs tasks, repeats trials, reduces them to pass^k and records every model call. Its built-in numeric match only accepts exact equality, so a grader with per-figure tolerance and units is needed.

**Decision.** The exam is an Inspect task. The hand-written agent loop runs inside it through Inspect's agent bridge, with a per-question cost and message limit. The grader is ours: unit must match, value within the figure's tolerance, result correct, incorrect or not attempted.

## Considered options

- A hand-written exam runner: rejected; plumbing that teaches little.

## Consequences

- The grader is tested first against hand-written fake submissions, before any agent exists.

## Why

*Lalit writes this section, in plain words, as part of ticket 6. Answer: what does the runner give you for free, and what must stay yours?*
