# The agent loop is written by hand on the Messages API; LangGraph comes later only as a comparison

Status: accepted (2026-10-14)

An agent loop is about 80 lines: call the model, run the tools it asks for, send results back, repeat. Frameworks hide the message format, tool errors, stop conditions and budgets, which is exactly what this project is for learning. Anthropic's guidance recommends starting with the API directly.

**Decision.** P1's agent loop is hand-written on the Anthropic Messages API, with Claude Sonnet 5.5. In P3 the multi-agent version is rebuilt in LangGraph and compared on the same exam.

## Considered options

- LangGraph from the start: rejected; hides what P1 is meant to teach.
- The SDK's tool runner: rejected for the same reason.

## Consequences

- The loop owns budgets, nudges, thinking-block pass-through and stop-reason handling itself (see `docs/research/p1-references.md`).

## Why

*Lalit writes this section, in plain words, as part of ticket 7. Answer: what did writing the loop yourself show you that a framework would have hidden?*
