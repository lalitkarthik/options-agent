# The agent finishes only by calling `submit_answer`, which the loop checks

Status: accepted (2026-10-14)

Good harnesses (Inspect's react agent, SWE-agent) end on an explicit submit tool, not on parsing text. Claude Sonnet 5.5 cannot be forced to call a tool, so the instructions must say so and the loop must handle a model that stops early.

**Decision.** The only successful exit is a `submit_answer` call with a strict schema. The loop checks the submission with guardrails (every number matches a figure a tool returned) and returns a tool error when one fails, so the model can fix it. A model that stops without submitting gets at most two nudges; then the outcome is "no submission". The loop fills `sources` itself from the cited figure ids.

## Considered options

- The API's structured output for the final reply: second choice; valid JSON, but no chance to reject and retry inside the loop.
- Parsing the final text: rejected; the weakest option.

## Consequences

- Invented numbers become a deterministic failure the model gets a chance to correct.
- The answer form must follow the API's schema limits: every field required, no numeric bounds, no field called "reasoning".

## Why

*Lalit writes this section, in plain words, as part of ticket 8. Answer: why is a checked tool call better than asking for JSON at the end?*
