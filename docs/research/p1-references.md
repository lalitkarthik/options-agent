# P1 references: agent loop, tools and MCP, evals

Research pass done on 2026-10-14 for phase P1 (agent core). It checks three open proposals
(Q6 answer form, Q15 tool set, Q17 ticket list) against primary sources: the code of reference
projects, official docs and specs, and papers. Every claim links to its source. Where a repo is
cited, the link is pinned to the commit that was read, with file and line numbers.

Nothing here is implementation code for `learn` tickets. Where a shape is described (an answer
schema, a task file), it is described in prose so the design stays Lalit's to write.

**Words used below, defined once**

- **Agent loop**: the `while` loop that sends the conversation to the model, runs any tools the
  model asks for, sends the results back, and repeats until a stop condition.
- **Turn**: one model call in that loop (plus the tool calls it asked for).
- **Stop reason** (`stop_reason`): the field in every Messages API response that says why the
  model stopped (`tool_use`, `end_turn`, `max_tokens`, `refusal`, ...).
- **Harness / scaffold**: the code around the model that runs the loop and the tools. An
  *evaluation harness* runs many tasks through it and grades them.
- **Grader / scorer**: code (or a model) that marks an answer right or wrong.
- **Trial / epoch**: one run of one task. Running each task 5 times gives 5 trials.
- **pass@k**: chance that at least one of k trials is correct. **pass^k** ("pass hat k"):
  chance that all k trials are correct; it measures consistency.
- **Abstention**: the agent says it cannot answer instead of guessing.
- **Structured output**: the API constrains the model's reply to a JSON schema (constrained
  decoding). **Strict tool use**: the same guarantee for a tool's input.
- **Provenance**: where a number came from (which snapshot, which as-of time, which tool call).
- **ACI (agent-computer interface)**: the tools and their outputs, seen as an interface designed
  for a model user (term from the SWE-agent paper).

---

## 1. Summary

### The most important findings

1. **Claude Sonnet 5.5 rejects forced tool use.** `tool_choice` of `any` or `tool` returns a 400
   error on Sonnet 5.5 (and Opus 5.5); only `auto` and `none` work. The docs say to use `auto`
   plus `strict: true` for schema-valid tool input, or structured outputs for a fixed JSON reply,
   and to say in the prompt when a tool applies
   ([What's new in Sonnet 5.5, "Forced tool use is not supported"](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5);
   [Define tools, "Forcing tool use"](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)).
   Any design that ends the loop by forcing a "submit" call will not work on the eval model.
2. **Sonnet 5.5 thinks by default and puts its between-tool notes in thinking blocks.** Those
   blocks must be passed back unchanged with the rest of the assistant turn; `thinking:
   {"type": "disabled"}` returns a 400 (use `between_tools` instead)
   ([What's new in Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5)).
   The loop must append `response.content` whole, never just the text.
3. **Every serious harness has a hard turn cap and a defined "out of budget" outcome.** OpenAI
   Agents SDK: `max_turns` default 10, raises `MaxTurnsExceeded` unless a handler supplies a
   fallback answer. SWE-agent: per-task cost limit (default $3; $4 in the paper), on exhaustion it
   auto-submits what it has. The official MCP client tutorial: `MAX_TOOL_TURNS = 10`. Anthropic's
   own docs loop and tutorial loop have **no cap**; do not copy that part (section 2).
4. **The best harnesses end on an explicit submit tool, not on parsed text.** Inspect's `react()`
   agent and SWE-agent both finish when the model calls `submit`; Inspect only accepts a submit
   call that returned without error, and nudges the model with a "continue" message when it stops
   calling tools. Text parsing ("FINAL ANSWER:", XML tags) is what the Vals finance benchmark and
   Anthropic's tool-eval notebook do, and Anthropic's own docs call regex-on-output a sign the
   decision "should have been a tool call" (section 2).
5. **Tool errors are results, not crashes.** MCP 2026-07-28 splits errors into protocol errors
   (unknown tool, malformed request) and tool execution errors returned with `isError: true` and
   an actionable message so the model can correct itself. The Python SDK v2 maps this to `raise
   ToolError(...)`, hides the text of unexpected exceptions, and warns never to *return* an error
   string, because it then looks like a successful answer (section 3).
6. **Few, high-level tools beat many thin wrappers, and output size must be capped.** Anthropic's
   tool-writing post, Anthropic's docs and the SWE-agent ablations all point the same way.
   SWE-agent's capped "summarised search" (max 50 hits, else "please narrow your search") beat both
   iterative search (12.4% resolved) and no search tool at all (15.7%) (section 3).
7. **MCP is now stateless and our tools already fit it.** The 2026-07-28 revision removed the
   `initialize` handshake and sessions; state, if needed, goes in explicit handles passed as tool
   arguments. Our tools are pure functions of `(date, expiry, ...)` over frozen snapshots, so no
   handles are needed. Tutorials and courses from before July 2026 (and the reference servers,
   which still pin the v1 SDK) show the old handshake and the old `FastMCP` class name (section 3).
8. **Negative marking is backed by the literature, but the penalty must be stated to the agent.**
   SimpleQA proposes exactly "+1 correct, 0 not attempted, -p wrong" as a loophole-free single
   number; Kalai et al. (2025) show a penalty of t/(1-t) makes "answer only if more than t
   confident" the optimal policy and argue the threshold must be written into the instructions.
   With -3 for wrong, t = 0.75 (section 4).
9. **Inspect already has a pass^k reducer** (`pass_k`, the C(c,k)/C(n,k) estimator from
   tau-bench) next to `pass_at`, plus per-sample cost limits and an `agent_bridge()` that can run a
   hand-written Anthropic-SDK loop while Inspect records every model call. Its built-in numeric
   `match()` compares for exact equality and refuses to equate `60%` with `60`, so tolerance
   grading needs a custom scorer (section 4).
10. **Reference answers and graders are the usual failure point.** tau2-bench shipped fixes to 27
    airline tasks and re-graded old runs; Anthropic reports Opus 4.5 going from 42% to 95% on
    CORE-Bench once rigid grading ("96.12" rejected against "96.124991...") and task bugs were
    fixed. Version the task set and re-grade logs when it changes (section 4).

### Verdict on Q6 (answer form): keep the content, change the delivery and three fields

**Keep:** the `status` (answered / cannot_answer), prose `answer`, a `numbers` list with a fixed
unit enum, `missing_data`, and dropping self-reported confidence in favour of negative marking.
Kalai et al. 2025 §4.2 argue for "behavioral calibration" (answer or abstain at a stated
threshold) instead of asking the model for a probability, and SimpleQA's grading is exactly
correct / incorrect / not attempted.

**Change how it is returned: a dedicated `submit_answer` tool with `strict: true`, called under
`tool_choice: auto`, as the loop's only success exit.** Evidence:

- It is what Inspect `react()` and SWE-agent do (submit tool ends the loop), and both handle the
  "model stopped without submitting" case with a continue prompt or an autosubmit.
- Forcing the call is impossible on Sonnet 5.5 (finding 1), so the design must work under `auto`:
  say in the system prompt that the only way to finish is `submit_answer`, and if the model ends
  its turn without calling it, append a short continue message (Inspect's default text is in
  `_types.py` lines 49-51) and allow at most one or two such nudges.
- Because the submission is a tool call, the loop can **validate it and return `is_error: true`**
  with a precise message when it fails a guardrail (for example a number that does not appear in
  any tool result). Inspect only counts a submit call "with no error" as the answer
  (`_react.py` lines 198-210). That turns "no invented numbers" into a deterministic check the
  model gets a chance to fix.
- The API's structured output (`output_config.format`) is a valid second choice, and it is what
  the OpenAI Agents SDK uses (`output_type` is sent as a JSON-schema response format and the final
  output is the first text turn with no tool calls). It guarantees valid JSON but gives no hook to
  reject and retry inside the loop, and it is cached and compiled per schema. Parsing free text is
  the weakest option.

**Change three fields:**

1. `from_tool_call` should point to a **short, readable figure id that the tool itself returns**
   (for example `skew:2026-03-18:2026-04-17:put25`), not the opaque `toolu_...` id. Anthropic found
   that resolving opaque IDs into meaningful identifiers "significantly improves Claude's precision
   in retrieval tasks by reducing hallucinations" ([Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents)).
2. `sources` should be **filled by the harness**, not written by the model: every figure id maps to
   a snapshot and an as-of time, so the loop can derive `sources` from the cited figures. One less
   thing for the model to get wrong (the "poka-yoke your tools" advice in
   [Building effective agents, Appendix 2](https://www.anthropic.com/engineering/building-effective-agents)).
3. Decide now how **derived numbers** (a difference or ratio the model computes, such as IV minus
   RV) are reported. Either a tool returns the comparison precomputed, or a number entry carries
   its input figure ids and an operation from a small enum so the guardrail can recompute it.
   FinQA grades by executing the model's program rather than trusting its arithmetic
   ([FinQA evaluate.py](https://github.com/czyssrs/FinQA/blob/0f16e28/code/evaluate/evaluate.py#L444)).

**Schema rules the API imposes** ([Structured outputs, "JSON Schema limitations"](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)):
make every property required with `additionalProperties: false` (at most 24 optional and 16
union-typed parameters across all strict schemas); no `minimum`/`maximum`/`minLength`; arrays may
only use `minItems` 0 or 1; enum casing is not guaranteed, so compare unit enums case-insensitively
and avoid values that differ only by case. Do not name any field "reasoning" or ask for
step-by-step thinking: that can trigger a `reasoning_extraction` refusal on these models (same
page, "Invalid outputs"; [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)).

**Also state the penalty in the system prompt**, in the words of Kalai et al. 2025 §4.2: answer
only if more than 75% confident, since a wrong answer costs 3 points, a correct one earns 1, and
"cannot answer" earns 0.

### Verdict on Q15 (tools): keep about seven high-level tools, tighten their contracts

**Keep** the high-level set. Anthropic: "More tools don't always lead to better outcomes", build
"a few thoughtful tools targeting specific high-impact workflows", consolidate chained steps
([Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents)); the
API docs say "Consolidate related operations into fewer tools"
([Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)).
Serving precomputed figures is the "get_customer_context instead of three getters" pattern from
that post.

**Change:**

1. **Names as verb_noun** (`get_skew`, `get_realised_vol`, `get_implied_move`,
   `get_gamma_exposure`, `get_chain`, `list_dates`, `list_expiries`), matching the reference servers
   (`read_text_file`, `list_directory`) and the spec's naming rules
   ([tools.mdx lines 309-316](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/server/tools.mdx#L309-L316)).
   Make parameters unambiguous and enumerated: `kind` and `scope` become enums with documented
   values (Anthropic: name `user_id`, not `user`; "enforcing with strict data models").
2. **Every result carries provenance**: snapshot id, as-of time as an ISO 8601 timestamp with the
   New York offset (15:45 is -04:00 or -05:00 depending on DST), engine/build version, units per
   number, and the figure ids from Q6.
3. **Two kinds of "no data", handled differently.** An invalid input (a date with no snapshot, an
   unknown expiry) is a tool execution error that lists the valid values, so the model can retry,
   like the spec's example "must be in the future. Current date is ..."
   ([tools.mdx lines 738-785](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/server/tools.mdx#L738-L785)).
   A valid request whose figure does not exist (for example no gamma flip in range) is a normal
   result that says so explicitly, so the agent can choose `cannot_answer`.
4. **Cap `get_chain`**: a default and a maximum for `strikes_each_side`, concise columns, and a
   truncation note that says how to narrow the request (SWE-agent's 50-hit cap; the reference
   `fetch` server's `max_length`/`start_index` and "Content truncated. Call the fetch tool with a
   start_index of ..." message).
5. **Tool annotations** `readOnlyHint: true`, `openWorldHint: false` (the spec defaults are the
   opposite: `readOnlyHint` false, `openWorldHint` true;
   [schema.ts lines 1918-1953](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/schema/2026-07-28/schema.ts#L1918-L1953)).
6. **Descriptions written like a note to a new hire**: units (decimal vol or vol points), the delta
   convention behind "25-delta", how the forward is defined, what the tool does not return.
   Anthropic calls description writing "one of the most effective methods for improving tools".
7. **Return types declared** (Pydantic models), so the SDK publishes an `outputSchema` and fills
   `structuredContent` for tests and the harness while the model reads the JSON text
   ([SDK structured output docs](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/servers/structured-output.md)).

### Verdict on Q17 (tickets): keep the split, reorder two things, add four missing pieces

The learn/glue split matches the roadmap rule ("learn: the first time a concept appears").
Changes, with evidence:

1. **Move eval work earlier.** Split ticket 8 into **8a** (question set, reference answers,
   scorer, tested against hand-written fake answers; needs only the snapshots, so it can follow
   ticket 3 or 4) and **8b** (run the agent through Inspect with 5 epochs, pass^k and cost).
   Anthropic: "Step 0. Start early ... 20-50 simple tasks" and "eval-driven development"
   ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents));
   the tools post builds the eval before optimising the tools.
2. **Ticket 6 must name the MCP client side explicitly**: launching the server over stdio,
   listing tools, converting MCP tool definitions to Anthropic tool definitions, forwarding
   `is_error`. That is a first-time concept (so `learn`), and the official
   [Build an MCP client](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-client)
   tutorial is exactly this code. Ticket 6 also owns the budgets (turn cap, token cap, cost cap),
   parallel tool calls, thinking-block pass-through and stop-reason handling.
3. **Ticket 5 (remaining tools) can stay `glue` for the plumbing, but the tool descriptions and
   error messages are prompt engineering**, which Anthropic ranks among the highest-impact work.
   Either Lalit writes the descriptions, or the ticket's review checklist covers them.
4. **Missing from the list, though in the roadmap's P1 row:**
   - Streamable HTTP transport ("MCP (stdio, then streamable HTTP)"): no ticket.
   - Prompt caching: no ticket (it fits in ticket 6 or as a small learn ticket; the MCP spec now
     asks servers to list tools in a deterministic order partly to help prompt caching).
   - Exam v2 (~30 tasks) and an LLM judge (roadmap concepts): no ticket. The judge, if any, should
     only check that the prose `answer` does not contradict the graded numbers.
   - `CONTEXT.md` glossary (figure definitions, units enum): the roadmap says it comes from P1
     design; ticket 4 needs it before the first tool description is written.
5. **Tracing target is inconsistent**: the roadmap's P1 row says "self-hosted Langfuse", the P1 plan this
   research was asked to check says Langfuse Cloud. The Langfuse Python SDK is now v4 (4.17.0, 2026-10-05) and some v4 API
   methods require a v4 server; Cloud avoids that question in P1. Decide and update the roadmap.

---

## 2. Area 1: the agent loop

### 2.1 Anthropic docs, cookbooks and "Building effective agents"

**What it is.** The official Messages API docs (read 2026-10-14), the
`anthropics/claude-cookbooks` repo (commit `39cd5a7`, 2026-10-13), and the Dec 2024 post
"Building effective agents" (Schluntz and Zhang; page modified 2026-08-10).

**How it does the loop.**

- Canonical shape: "while `stop_reason == "tool_use"`, execute the tools and continue"; the loop
  exits on any other stop reason (`end_turn`, `max_tokens`, `stop_sequence`, `refusal`)
  ([How tool use works, "The agentic loop"](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)).
- Stop conditions: the post says tasks often end on completion but "it's also common to include
  stopping conditions (such as a maximum number of iterations) to maintain control"
  ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
  The docs' sample loops (`while True` in
  [Stop reasons, "Handling tool use workflows"](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons))
  and the [tutorial](https://platform.claude.com/docs/en/agents-and-tools/tool-use/build-a-tool-using-agent)
  have no cap.
- Other stop reasons: `max_tokens` (a cut-off `tool_use` block must be retried with a larger
  `max_tokens`), `refusal` (HTTP 200, read `stop_details`), `model_context_window_exceeded`
  (treat as truncated), and empty `end_turn` responses, usually caused by adding text after
  `tool_result` blocks ([Stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)).
- Tool errors: return a `tool_result` with `is_error: true` and the message; for invalid calls
  "Claude will retry 2-3 times with corrections before apologizing to the user"
  ([Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)).
- Parallel calls: one response can hold several `tool_use` blocks; the order of execution is
  yours; return **one** `tool_result` per call, all in the **next single user message**, results
  before any text; a call you chose not to run still gets `is_error: true`
  ([Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)).
- Final answer: the cookbook's tool-evaluation agent (cell 3 prompt, cell 5 loop, cell 8 scoring
  in [`tool_evaluation.ipynb`](https://github.com/anthropics/claude-cookbooks/blob/39cd5a7/tool_evaluation/tool_evaluation.ipynb))
  asks for `<response>` tags, regex-extracts the last one, and scores by exact string match,
  with `NOT_FOUND` as the abstain answer. The same docs say: "if you're writing a regex to extract
  a decision from model output, that decision should have been a tool call"
  ([How tool use works, "When to use tools"](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)).
- Frameworks: "start by using LLM APIs directly ... If you do use a framework, ensure you
  understand the underlying code" (Building effective agents), which supports the hand-written loop.

**Take.** The stop-reason `match` (handle every value, not just `tool_use`/`end_turn`); all tool
results in one user message with nothing after them; `is_error` for failures; tracking per-tool
call counts and durations (the cookbook records them, and the tools post recommends logging
"total runtime ... number of tool calls ... token consumption, and tool errors").

**Do not take.** The uncapped `while` loops. The cookbook loop's `next(block ...)` that runs only
the **first** `tool_use` block (it breaks on parallel calls) and its `eval(f"{tool_name}(...)")`
dispatch (the notebook itself warns against it). XML-tag answer extraction.

### 2.2 OpenAI Agents SDK

**What it is.** `openai/openai-agents-python`, version 0.23.1, commit `1c1a28d` (2026-10-14).

**How it does the loop.**

- Loop: call the model; if the output counts as final, stop; if it is a handoff, switch agent;
  else run the tool calls and loop
  ([`run.py` lines 300-311](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/run.py#L300-L311);
  [`docs/running_agents.md` lines 34-45](https://github.com/openai/openai-agents-python/blob/1c1a28d/docs/running_agents.md#L34-L45)).
- Final output detection: "it produces text output with the desired type, and there are no tool
  calls" (same doc). With an `output_type` the text is validated against the JSON schema
  ([`turn_resolution.py` lines 1176-1300](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/run_internal/turn_resolution.py#L1176-L1300));
  the schema is sent as a strict `json_schema` response format
  ([`openai_responses.py` lines 2107-2110](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/models/openai_responses.py#L2107-L2110)).
  An empty structured answer leads to another turn; an invalid one raises `ModelBehaviorError`
  unless an `invalid_final_output` handler supplies a fallback.
- Alternative endings: `tool_use_behavior` can be `"stop_on_first_tool"` or `StopAtTools`, which
  makes a named tool's output the final answer
  ([`agent.py` lines 396-410](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/agent.py#L396-L410)).
- Turn budget: `DEFAULT_MAX_TURNS = 10`
  ([`run_config.py` line 45](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/run_config.py#L45));
  a turn is "one AI invocation (including any tool calls)"; exceeding it raises
  `MaxTurnsExceeded` ([`run.py` lines 1597-1606](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/run.py#L1597-L1606)),
  or an `error_handlers={"max_turns": ...}` callback returns a controlled answer
  ([`running_agents.md` lines 478-509](https://github.com/openai/openai-agents-python/blob/1c1a28d/docs/running_agents.md#L478-L509)).
- Runaway tool use: `reset_tool_choice=True` by default "ensures that the agent doesn't enter an
  infinite loop of tool usage" when a tool was forced
  ([`agent.py` lines 418-420](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/agent.py#L418-L420)).
- Tool errors: by default the model gets a fixed "An error occurred while running the tool.
  Please try again." without the exception text
  ([`tool.py` lines 1997-2002](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/tool.py#L1997-L2002)).
- Parallel tools: run concurrently with `asyncio` tasks (`tool_execution.py`).

**Take.** A default turn cap of about 10 and a named outcome when it is hit (we score it as
"no submission"). Treating "invalid final answer" as its own error kind. The idea that one named
tool can end the run.

**Do not take.** The generic hidden error message: our tool errors are written for the model and
should be shown (MCP spec, section 3). The framework itself, per the roadmap (LangGraph is the P3
comparison, not this).

### 2.3 SWE-agent

**What it is.** `SWE-agent/SWE-agent` v1.1.0, commit `3ea751c` (2026-07-16), and the paper
"SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering" (Yang et al.,
arXiv 2405.15793 v3, revised 2024-11-11).

**How it does the loop.**

- Ends on a `submit` command (`submit_command: str = "submit"`,
  [`tools/tools.py` line 109](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/tools/tools.py#L109)).
  The default config adds a review step: the first `submit` returns a checklist and the diff and
  asks the agent to "Run the submit command again to confirm"
  ([`config/default.yaml` lines 44-62](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/config/default.yaml#L44-L62)).
- Budgets: `per_instance_cost_limit` default 3.0 (dollars), `total_cost_limit`,
  `per_instance_call_limit`
  ([`models.py` lines 73-78](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/agent/models.py#L73-L78));
  command `execution_timeout` 30 s, `total_execution_timeout` 1800 s, at most 3 consecutive
  timeouts ([`tools.py` lines 139-150](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/tools/tools.py#L139-L150)).
  The paper used $4 per task: "if a run exceeded this budget, existing edits were submitted
  automatically".
- Errors split in two
  ([`agents.py` lines 1076-1218](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/agent/agents.py#L1076-L1218)):
  *requery* errors (malformed output, blocked command, bad shell syntax) send an error template
  back and retry up to `max_requeries = 3`; *exit* errors (cost limit, context window, timeouts,
  API retry failure, environment crash) stop the run and **autosubmit** with an `exit_status`
  such as `exit_cost` or `exit_format`.
- Output control: observations over 100,000 characters are clipped with a note telling the agent
  to use a narrower command
  ([`agents.py` lines 69-79](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/agent/agents.py#L69-L79));
  an empty output becomes "Your command ran successfully and did not produce any output"
  ([`default.yaml` lines 29-30](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/config/default.yaml#L29-L30)).
- Paper finding, §5.2: "Agents succeed quickly and fail slowly": resolved runs had a median of
  $1.21 and 12 steps versus a mean of $2.52 and 21 steps for failures, and 93.0% of resolved runs
  submitted before the budget ran out, so raising the budget "is unlikely to substantially
  increase performance".

**Take.** Every way the loop can end gets a named `exit_status` that is logged and graded. A
small retry budget for malformed calls separate from the turn budget. The "fail slowly" result
justifies a tight turn cap. The empty-result message idea: a tool should never return nothing.

**Do not take.** Autosubmitting a partial answer: in our scoring a forced answer could be wrong
and cost -3, so running out of budget should become "no submission" (scored like
`cannot_answer`, reported separately). The double-submit review step is useful for code patches,
not for a single answer.

### 2.4 Inspect AI `react()` agent

**What it is.** `UKGovernmentBEIS/inspect_ai` 0.3.280, commit `86c1157` (2026-10-14).

**How it does the loop** ([`agent/_react.py`](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/agent/_react.py)):

- "The agent runs a tool use loop until the model submits an answer using the `submit()` tool"
  (lines 80-89). The default submit tool takes one string `answer` (lines 157-167); its output is
  never truncated because "The submit result becomes the completion" (lines 183-191).
- Only a submit call **without an error** counts (lines 198-210).
- If the model stops calling tools, a continue message is added: "Please proceed to the next step
  using your best judgement. If you believe you have completed the task, please call the
  `{submit}()` tool with your final answer." (lines 375-416; text in
  [`_types.py` lines 49-51](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/agent/_types.py#L49-L51)).
- The loop itself has no turn counter: it "will terminate after submit ... or if a message or
  token limit is hit" (lines 259-260); limits are set on the task or sample (`message_limit`,
  `token_limit`, `time_limit`, and `cost_limit`, which needs model price data;
  [`docs/setting-limits.qmd` lines 184-203](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/setting-limits.qmd#L184-L203)).
  Three consecutive content-filter refusals also stop it (lines 284-292).
- Optional `attempts`: score each submission and, if wrong, reply "Your submission was incorrect"
  ([`_types.py` lines 68-88](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/agent/_types.py#L68-L88)).
- Parallel calls are encouraged in the default system prompt (`PARALLEL_TOOLS_PROMPT`, line 13).
- Tool errors: `ToolError` and a few expected exceptions are reported to the model; unexpected
  exceptions fail the sample ([`docs/tools-custom.qmd` lines 16-45](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/tools-custom.qmd#L16-L45)).

**Take.** Submit-tool ending, "only an error-free submit counts", a fixed continue message with a
small retry count. Also: Inspect can run its own `react()` against our MCP server directly
(`mcp_server_stdio`, [Inspect MCP docs](https://inspect.aisi.org.uk/tools-mcp.html)), which gives
a cheap **baseline agent** to compare the hand-written loop with.

**Do not take.** `attempts` with feedback "your submission was incorrect": it leaks the grade into
the run and would make the eval measure something other than the production agent. The free-text
`answer: str` submit signature: ours is a typed object.

### 2.5 The official MCP client tutorial (bonus: closest to what ticket 6 builds)

[`quickstart-resources/mcp-client-python/client.py`](https://github.com/modelcontextprotocol/quickstart-resources/blob/470d1ba/mcp-client-python/client.py)
(commit `470d1ba`, 2026-09-20) connects with the v2 `Client` over stdio (`mode="auto"` probes
`server/discover` and falls back to the old handshake), turns each MCP tool into an Anthropic tool
(`name`, `description`, `input_schema`), loops at most `MAX_TOOL_TURNS = 10` times, forwards
`is_error` from the MCP result, and passes only the text blocks of `content` to the model while
`structured_content` stays available to the application.

**Take.** All of it as the reference for ticket 6. **Do not take** its "concatenate all text into
the final answer" ending; our ending is `submit_answer`.

### 2.6 Area 1 answers in one table

| Question | What the references do | For P1 |
|---|---|---|
| Stop condition | Inspect, SWE-agent: submit tool. OpenAI SDK: text with no tool calls (or a stop-at tool). Anthropic docs: any stop reason other than `tool_use` | Success = valid `submit_answer`. Every other ending gets a named status |
| Turn budget | OpenAI 10; MCP tutorial 10; Inspect via message/token limits; SWE-agent via cost | Cap turns (start at 10-12), cap `max_tokens` per call, cap dollars per question |
| Cost budget | SWE-agent $3 default; Inspect `cost_limit` per sample | Per-question cost limit in Inspect; log cost per trial |
| Tool errors | `is_error` / `ToolError` shown to the model; unexpected crashes hidden or fail the sample | Same; malformed-call retries counted separately (SWE-agent's 3) |
| Parallel calls | Default on; all results in one user message | Run all `tool_use` blocks (tools are read-only, so concurrently is safe) |
| Final answer | Submit tool (Inspect, SWE-agent), structured output (OpenAI), tags/marker (cookbook, Vals) | Strict `submit_answer` tool, validated in the loop |
| Runaway loops | Turn caps, consecutive-refusal cap, timeouts, "succeed quickly, fail slowly" | Turn cap + nudge cap + cost cap; log `exit_status` |

---

## 3. Area 2: tool and MCP server design

### 3.1 Anthropic: "Writing effective tools for agents — with agents"

**What it is.** Anthropic engineering post by Ken Aizawa et al., published 2025-09-11 (modified
2026-01-06): [link](https://www.anthropic.com/engineering/writing-tools-for-agents).

**What it says.**

- High-level beats low-level: tools that "merely wrap existing software functionality or API
  endpoints" are a common error; prefer `search_contacts` over `list_contacts`,
  `get_customer_context` over three getters; "Too many tools or overlapping tools can also
  distract agents".
- Naming: namespace by service and resource; prefix versus suffix "non-trivial effects", test it.
- Return "only high signal information"; natural-language identifiers over UUIDs; optionally a
  `response_format` enum (`concise` / `detailed`); "there is no one-size-fits-all" between JSON,
  XML and Markdown.
- Size: "pagination, range selection, filtering, and/or truncation with sensible default
  parameter values"; Claude Code caps tool responses at 25,000 tokens by default; truncation and
  error messages should steer the agent ("clearly communicate specific and actionable
  improvements, rather than opaque error codes or tracebacks").
- Descriptions: write them as for a new hire, make niche terminology explicit, unambiguous
  parameter names.
- Process: prototype, then evaluate with realistic multi-call tasks, verifiable answers, and
  "avoid overly strict verifiers"; keep a held-out test set.

**Take.** All of the principles above; the eval-first loop of improving tool descriptions.
**Do not take** the `response_format` enum for now: with seven tools over small precomputed
figures it adds a parameter without a measured need.

The API docs restate the same rules (detailed descriptions of 3-4+ sentences, consolidate
operations, "high-signal information", `input_examples` for complex inputs) in
[Define tools, "Best practices"](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).

### 3.2 SWE-agent paper: ACI findings

From [arXiv 2405.15793 v3](https://arxiv.org/pdf/2405.15793v3) (§2 principles, §3 design, §5
ablations, Table 3):

- Principle: "Guardrails mitigate error propagation and hasten recovery" (a syntax check that
  rejects a broken edit).
- Capped output: "The search commands return at most 50 results for each search query; if a
  search exceeds this number, we do not report the results and instead suggest that the agent
  write a more specific query" (code: [`search_dir` lines 28-31](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/tools/search/bin/search_dir#L28-L31),
  now at 100 files).
- Iterative search (results shown one at a time) did worse than no search tool, 12.4% versus 15.7%
  resolved, because agents paged through every match and exhausted their budget.
- File viewer: 100-line windows beat 30 lines (14.3%) and the whole file (12.7%).
- Context: older observations are collapsed to one line each, keeping the last 5 in full.
- "Any attempt at editing has a 90.5% chance of eventually being successful. This probability
  drops off to 57.2% after a single failed edit": recoverable errors matter.

**Take.** Hard caps with a "narrow your request" message; never return empty output; validate
inputs at the tool. **Do not take** history collapsing: our runs are short (about 10 turns).

### 3.3 MCP specification 2026-07-28

**What it is.** The protocol spec, read from `modelcontextprotocol/modelcontextprotocol` commit
`5ea9960` (2026-10-13); released 2026-07-28
([release post](https://blog.modelcontextprotocol.io/posts/2026-07-28/)).

**Relevant parts.**

- Changelog ([`changelog.mdx`](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/changelog.mdx)):
  no `initialize` handshake, no `Mcp-Session-Id`; protocol version and client capabilities travel
  in `_meta` on every request; new `server/discover`; every result has `resultType`; servers
  "SHOULD return tools from `tools/list` in a deterministic order" (for client caching and prompt
  cache hits); OpenTelemetry trace context keys (`traceparent`, `tracestate`, `baggage`) in
  `_meta` are documented; `inputSchema`/`outputSchema` allow any JSON Schema 2020-12 keyword;
  Roots, Sampling and Logging are deprecated ("log to `stderr` (stdio) or use OpenTelemetry
  instead of Logging").
- Tool fields: `name`, `title`, `description`, `inputSchema` (for no parameters the recommended
  form is `{"type": "object", "additionalProperties": false}`), optional `outputSchema`,
  `annotations`
  ([`tools.mdx` lines 280-303](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/server/tools.mdx#L280-L303)).
- Structured content: any JSON value conforming to `outputSchema`; "a tool that returns structured
  content SHOULD also return the serialized JSON in a TextContent block"; servers MUST conform to
  the output schema and clients SHOULD validate (lines 496-516).
- Stateful tools (non-normative): with no session, keep state behind an explicit handle returned
  by a creation tool and passed back as an argument; handles should be opaque, state their
  lifetime in the description, and an expired handle should give a tool execution error "so the
  model can recover" (lines 683-736).
- Errors: protocol errors (unknown tool, malformed request, server errors) as JSON-RPC errors
  versus tool execution errors with `isError: true` and "actionable feedback"; clients "SHOULD
  provide tool execution errors to language models to enable self-correction" (lines 738-785).
- Annotations are hints and "clients MUST consider tool annotations to be untrusted unless they
  come from trusted servers"; defaults `readOnlyHint: false`, `destructiveHint: true`,
  `idempotentHint: false`, `openWorldHint: true`
  ([`schema.ts` lines 1918-1953](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/schema/2026-07-28/schema.ts#L1918-L1953)).
- stdio transport: newline-delimited messages, and "The server MUST NOT write anything to its
  `stdout` that is not a valid MCP message" ([`stdio.mdx` lines 13-20](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/basic/transports/stdio.mdx#L13-L20)).

**Take.** Tool execution errors for anything the model can fix; deterministic tool order;
annotations set explicitly; text plus structured content; trace context in `_meta` when tracing
across client and server. **Do not take** handles: there is no cross-call state to keep.

### 3.4 MCP Python SDK v2

**What it is.** `modelcontextprotocol/python-sdk`, latest release v2.3.0 (2026-10-02), docs read
at commit `754254c` (2026-10-13); site [py.sdk.modelcontextprotocol.io](https://py.sdk.modelcontextprotocol.io/).

**What matters for P1.**

- v2 speaks the 2026-07-28 protocol; `FastMCP` is renamed `MCPServer` and the old import path is
  gone; a first-class `Client` replaces the transport + `ClientSession` + `initialize()` stack
  ([`docs/whats-new.md`](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/whats-new.md)).
  Most tutorials written before July 2026 use the v1 names.
- Testing in memory: `Client(server)` connects to the server object directly, "No subprocess. No
  port."; `raise_exceptions=True` shows real crash messages in tests; uses `pytest` with the anyio
  plugin ([`docs/get-started/testing.md`](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/get-started/testing.md)).
- Errors ([`docs/servers/handling-errors.md`](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/servers/handling-errors.md)):
  `ToolError` means "the model sees your message" (`is_error=True`); `MCPError` is a protocol
  error the model never sees; any other exception becomes a generic `is_error=True` result and a
  logged traceback. Rule of thumb: "could a smarter model have avoided this? Yes -> `ToolError`."
  "Never `return` an error message from a tool." Bad arguments are rejected against the input
  schema before your function runs.
- Structured output: the return type annotation **is** the output schema; `content` "is for the
  model", `structured_content` "is for the application"
  ([`docs/servers/structured-output.md`](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/servers/structured-output.md)).
- Annotations: `read_only_hint=True`, `open_world_hint=False` for a closed catalog
  ([`docs/servers/tools.md` lines 143-160](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/servers/tools.md#L143-L160)).
- Tracing is built in: every handled message is an OpenTelemetry span; `tools/call` spans carry
  `gen_ai.operation.name = "execute_tool"` and `gen_ai.tool.name`; it costs nothing until an
  OpenTelemetry SDK and exporter are installed
  ([`docs/run/opentelemetry.md`](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/run/opentelemetry.md)).
- stdio gotcha: an import-time `print()` corrupts the protocol stream; log to stderr
  ([`docs/get-started/real-host.md` line 163](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/get-started/real-host.md#L163)).

**Take.** In-memory `Client` tests as the TDD loop for tickets 4 and 5; `ToolError` versus crash;
Pydantic return types. **Do not take** `Resolve`/elicitation or multi-round-trip requests: there
is no user to ask mid-call.

### 3.5 Reference servers (`modelcontextprotocol/servers`)

**What it is.** Commit `bbb701e` (2026-10-11). Note: these still pin the v1 SDKs (`fetch`:
`mcp>=1.29.0,<2`; `filesystem`: `@modelcontextprotocol/sdk ^1.31.0`), so their API calls are not v2.

- Naming and annotations: `read_text_file` with `title`, a long description saying when to use
  it and its `head`/`tail` limits, `outputSchema`, and `readOnlyHint: true, openWorldHint: false`
  ([`filesystem/server.ts` lines 268-292](https://github.com/modelcontextprotocol/servers/blob/bbb701e/src/filesystem/server.ts#L268-L292)).
- Output size: `fetch` has `max_length` (default 5000) and `start_index`, and appends "Content
  truncated. Call the fetch tool with a start_index of N to get more content."
  ([`fetch/server.py` lines 353-372 and 476-478](https://github.com/modelcontextprotocol/servers/blob/bbb701e/src/fetch/src/mcp_server_fetch/server.py#L353-L372)).

**Take.** Description style, explicit annotations, truncation that tells the model the next call.
**Do not take** `fetch`'s use of `McpError` (a protocol error) for failures the model could act
on; under the 2026-07-28 rules those should be tool execution errors.

### 3.6 Area 2 answers

- **High-level versus low-level:** high-level, few tools (3.1, 3.2, Define tools docs).
- **Naming:** verb_noun, 1-128 characters of `[A-Za-z0-9_-.]`, unique, unambiguous parameters.
- **Errors the agent can recover from:** `isError: true`, message says what was wrong and what is
  valid (list the available dates/expiries); hide internals of real crashes.
- **Output size:** small by design; caps with defaults; a truncation note with the next call;
  25k tokens is Claude Code's hard ceiling, ours should be far below it.
- **Provenance:** in every result (snapshot id, timezone-aware as-of, engine version, units,
  figure ids), in both the JSON text and `structuredContent`.
- **Stateless handles:** not needed; all inputs are explicit arguments.

---

## 4. Area 3: evals and answer grading

### 4.1 Inspect AI

**What it is.** UK AISI's eval framework, 0.3.280 (2026-10-14), commit `86c1157`;
docs at [inspect.aisi.org.uk](https://inspect.aisi.org.uk/).

- **Structure:** a `Task` = dataset of `Sample`s (input, target, metadata) + solver/agent +
  scorer(s); `Task(version=...)` exists to "distinguish evolutions" of a task
  ([`task.py` line 120](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/_eval/task/task.py#L120)).
- **Epochs and reducers:** run each sample N times and reduce with `mean`, `mode`, `median`,
  `max`, `at_least_k`, `pass_at_k` (Chen et al. 2021 estimator) and **`pass_k`** ("Probability that
  all `k` epoch attempts succeed", `C(correct, k) / C(total, k)`)
  ([`reducer.py` lines 163-246](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/scorer/_reducer/reducer.py#L163-L246);
  [`docs/metrics.qmd` lines 327-395](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/metrics.qmd#L327-L395)).
  Several reducers can run at once (`Epochs(5, ["mean", "pass_at_5"])`).
- **Code versus model scorers:** `match()`, `includes()`, `pattern()`, `exact()`, `f1()`, `math()`
  versus `model_graded_qa()` / `model_graded_fact()` ([`docs/_builtin-scorers.md`](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/_builtin-scorers.md)).
  `match(numeric=True)` strips `$ , * _` but then tests **equality**, and does not strip `%`:
  "`60%` is ambiguous (it could mean `60` or `0.6`)"
  ([`_match.py` lines 22-30](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/scorer/_match.py#L22-L30);
  [`_common.py` lines 89-111](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/scorer/_common.py#L89-L111)).
- **Running our own loop:** `agent_bridge()` runs a custom agent written against the Anthropic
  (or OpenAI, Google) Python API in-process; calls made with model name `"inspect"` are routed to
  the eval's model, so Inspect logs and limits them ([`docs/agent-bridge.qmd` lines 31-65](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/agent-bridge.qmd#L31-L65)).
- **Cost:** `cost_limit` per sample needs model price data; Sonnet 5.5 is in Inspect's model
  database (`_model_data/anthropic.yml` lines 187-202: release 2026-09-28, adaptive thinking on by
  default).
- **Logs and viewer:** every sample's full transcript, scores, token usage and timing are in the
  log, browsable with `inspect view` ([log viewer docs](https://inspect.aisi.org.uk/log-viewer.html)).

**Take.** Inspect as the harness; custom scorer; `Epochs(5, [...])` with `mean` and `pass_k`;
`agent_bridge` so the hand-written loop is the thing measured; `cost_limit` and `message_limit`
per sample; `react()` + `mcp_server_stdio` as a baseline. **Do not take** `match(numeric=True)` or
`model_graded_*` for the numbers.

### 4.2 tau2-bench (Sierra)

**What it is.** `sierra-research/tau2-bench` v1.0.1, commit `dd8757d` (2026-10-13); papers
tau-bench (arXiv 2406.12045, 2024) and tau2-bench (arXiv 2506.07982, 2025).

- **Task format:** JSON with `id`, a `description.purpose` ("Testing that agent refuses to proceed
  with a cancellation that is not allowed ..."), a user scenario, optional initial state, and
  `evaluation_criteria` (`data/tau2/domains/airline/tasks.json`, task 0).
- **Outcome grading:** the reward is the product of the components in `reward_basis`, default
  `[DB, COMMUNICATE]`; DB compares the final database state with the state produced by replaying
  the gold actions, so "any agent path producing an equivalent end state passes"; tool-call
  matching (`ACTION`) is used only in a few tasks
  ([`tasks.py` lines 237-262](https://github.com/sierra-research/tau2-bench/blob/dd8757d/src/tau2/data_model/tasks.py#L237-L262)).
  `COMMUNICATE` is a lowercase substring check with commas removed, marked "TODO: This could be
  improved!" ([`evaluator_communicate.py` lines 62-72](https://github.com/sierra-research/tau2-bench/blob/dd8757d/src/tau2/evaluator/evaluator_communicate.py#L62-L72)).
- **pass^k:** `math.comb(success_count, k) / math.comb(num_trials, k)`, success = reward within
  1e-6 of 1, computed for every k from 1 to the number of trials
  ([`agent_metrics.py` lines 12-16, 113-126](https://github.com/sierra-research/tau2-bench/blob/dd8757d/src/tau2/metrics/agent_metrics.py#L113-L126)).
- **Splits:** airline has `train` 30, `test` 20, `base` 50 (`split_tasks.json`).
- **Versioning:** SemVer for the package ([`VERSIONING.md`](https://github.com/sierra-research/tau2-bench/blob/dd8757d/VERSIONING.md));
  results files embed the task definitions, and `tau2 evaluate-trajs --fresh-tasks` re-grades old
  runs against fixed tasks; release notes warn that scores before and after a grading change "must
  not be compared", and list fixes to 27 airline and 26 retail tasks
  ([`CHANGELOG.md` lines 20-45, 169-180](https://github.com/sierra-research/tau2-bench/blob/dd8757d/CHANGELOG.md#L20-L45)).

**Take.** Grade the outcome (the submitted numbers and status), not the path; a `purpose` line
per task; pass^k for every k up to 5; a train/test split; store the task definition (and
version) with each result so old logs can be re-graded. **Do not take** substring matching for
numbers, or the user simulator (our questions are single-turn).

### 4.3 SimpleQA and its Inspect port

**What it is.** OpenAI's short-answer factuality benchmark: paper arXiv 2411.04368 (2024);
reference grader in `openai/simple-evals` commit `652c89d` (repo marked "no longer updated" since
July 2025 but still hosts SimpleQA); Inspect port in `UKGovernmentBEIS/inspect_evals` commit
`3df9015`, task version `5-D`.

- **Grades:** correct ("fully contains the reference answer without contradicting"), incorrect
  ("contradicts ... even if the contradiction is hedged"), not attempted (paper Table 2).
- **Numbers:** "the predicted answer needs to be correct to the last significant figure in the
  gold answer" ("120k" accepts 124k and 115k, rejects 113k)
  ([`simpleqa_eval.py` lines 60-67](https://github.com/openai/simple-evals/blob/652c89d/simpleqa_eval.py#L60-L67)).
- **Metrics:** overall correct, correct given attempted, and their harmonic mean (F-score)
  (lines 165-190). The paper notes the F-score's loophole (guessing pays when a model is at least
  50% sure) and proposes the alternative: "assign a specific negative penalty p to wrong answers
  ... correct is worth 1 point, not attempted is worth 0 points, and incorrect is worth -p points".
- **Inspect port:** the score value is a dict `{correct, incorrect, not_attempted}` and a custom
  metric derives `attempted`, `correct_given_attempted` and the F-score
  ([`simpleqa/scorer.py` lines 29-75](https://github.com/UKGovernmentBEIS/inspect_evals/blob/3df9015/src/inspect_evals/simpleqa/scorer.py#L29-L75)).

**Take.** The three-way outcome stored per sample as a dict, the "accuracy given attempted"
breakdown, the precision rule for numbers. Our net score (+1 / 0 / -3) is SimpleQA's own
loophole-free alternative with p = 3. **Do not take** the LLM grader: our answers are structured.

### 4.4 "Why Language Models Hallucinate", §4.2

Kalai, Nachum, Vempala, Zhang (OpenAI / Georgia Tech), arXiv 2509.04664 (Sep 2025):

- Proposed instruction: "Answer only if you are > t confident, since mistakes are penalized
  t/(1-t) points, while correct answers receive 1 point, and an answer of 'I don't know' receives
  0 points."
- "we propose making the confidence threshold explicit in the instructions"; without it "there is
  an inherent tradeoff, and no single model will be best".
- "Behavioral calibration": output the best answer at least t-confident, rather than a stated
  probability.

For our -3 penalty, t/(1-t) = 3 gives t = 0.75 (equivalently: answer when 1·p - 3·(1-p) > 0, i.e.
p > 0.75). The text extracted from the PDF pairs "t = 0.75" with "penalty 2", which contradicts
the paper's own formula; trust the formula and check the PDF.

### 4.5 Vals AI Finance Agent Benchmark

arXiv 2508.00828 (Aug 2025), the closest domain match:

- Harness: four tools (Google search, EDGAR search, ParseHTML into a key-value store,
  RetrieveInformation from it, the last two letting the model manage its own context); final
  answer by text marker: "respond with 'FINAL ANSWER:' followed by your answer" plus a `sources`
  dictionary.
- Errors: "retryable" errors (rate limits) are retried with backoff and not counted against the
  agent; "agent errors" (token limits, bad arguments) are returned as tool responses.
- Grading: LLM-as-judge with a rubric checked "against specific components of expert solutions
  rather than holistically", plus contradiction detection.
- Splits: public validation 50, private validation 150, private test 357, kept private "to prevent
  ... contamination". (The paper gives different totals in different places, 537 and 337.)
- Reports cost and time per task (o3: about 3.1 minutes and $3.78 per task).
- Failure modes: repeating a failing tool call without changing strategy; "hallucinating documents
  ... even when no such documents exist".

**Take.** The retryable-versus-agent-error split; sources required with every answer; held-out
questions; cost per question. **Do not take** the text marker or the LLM judge for numbers.

### 4.6 FinQA and TAT-QA official eval scripts

- **FinQA** (`czyssrs/FinQA`, commit `0f16e28`, 2022): converts strings to numbers by removing
  commas, treats `x%` as `x/100`, rounds executed results to 5 decimals and compares for equality
  ([`evaluate.py` lines 27-47, 186-188, 444](https://github.com/czyssrs/FinQA/blob/0f16e28/code/evaluate/evaluate.py#L27-L47)).
  It grades the model's *program* by executing it (execution accuracy).
- **TAT-QA** (`NExTplusplus/TAT-QA`, commit `870accc`, 2024): each answer has a `scale`
  (`""`, thousand, million, billion, percent); numbers are rounded to 2 decimals, multiplied by
  the scale and compared as 4-decimal strings; a bare `0.2342` is also accepted for `23.42` with
  scale `percent`; scale correctness is counted separately
  ([`tatqa_metric.py` lines 145-198, 244-267](https://github.com/NExTplusplus/TAT-QA/blob/870accc/tatqa_metric.py#L145-L198);
  [`tatqa_utils.py` lines 6-19](https://github.com/NExTplusplus/TAT-QA/blob/870accc/tatqa_utils.py#L6-L19)).

**Take.** Units/scale as a separate graded field (our unit enum); one canonical internal unit per
figure type; explicit percent handling. **Do not take** fixed global rounding: tolerance should
follow the precision the tool reports (SimpleQA's last-significant-figure rule).

### 4.7 Anthropic: "Demystifying evals for AI agents"

Grace, Hadfield, Olivares, De Jonghe; published 2026-01-09:
[link](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

- Vocabulary: task, trial, grader, transcript, outcome, evaluation harness, agent harness.
- Graders: prefer deterministic code graders; LLM judges "where necessary", calibrated against
  humans and given a way out ("Unknown").
- "20-50 simple tasks drawn from real failures is a great start"; a good task is one where "two
  domain experts would independently reach the same pass/fail verdict"; write a reference
  solution that passes all graders; 0% pass@100 usually means a broken task.
- **Balanced sets:** test where a behaviour should happen and where it should not.
- Grade the outcome, not the exact tool sequence; isolate trials (no shared state).
- Grading bugs: CORE-Bench "96.12" versus "96.124991..." took Opus 4.5 from 42% to 95% once fixed.
- pass@k versus pass^k: "pass^k ... especially matters for customer-facing agents"; at 75%
  per-trial success, pass^3 is about 42%.
- Track latency, tokens, cost per task and error rates; "Read the transcripts!"

### 4.8 Area 3 answers

- **Task + reference structure:** one record per question: id, question text, `purpose`,
  expected `status`, reference figures (name, value, unit, expiry, the snapshot they come from,
  and the tolerance), tags (figure type, answerable or not), and the task-set version. Write a
  reference "perfect submission" per task and check it scores +1 (Anthropic step 2).
- **Balanced:** include questions whose correct outcome is `cannot_answer` (a date not in the
  snapshots, a figure the engine does not produce). On those, `cannot_answer` must earn +1 and any
  numeric answer -3; otherwise abstention is never rewarded where it is right.
- **Numeric tolerance and units:** unit must match exactly (case-insensitive enum); value within a
  per-figure-type tolerance set at the precision the tool reports; percent stored as one canonical
  form. No LLM judge for numbers.
- **Abstention scoring:** +1 / 0 / -3, threshold stated to the agent (0.75); report correct,
  incorrect, not attempted, accuracy given attempted, and the net score.
- **Trials:** 5 epochs; report mean (pass^1) and pass^5 via `pass_k`, per task as well as overall
  (with 10 tasks, one task is 10 points).
- **Held-out set:** keep part of the questions unseen while tuning prompts and tool descriptions
  (tau2 train/test, Vals private test, Anthropic's held-out tool evals).
- **Task versioning:** an `N-X` version like inspect_evals (N bumps when results stop being
  comparable: any change to data, scoring, prompts or tolerance; X when the task interface changes)
  ([`TASK_VERSIONING.md`](https://github.com/UKGovernmentBEIS/inspect_evals/blob/3df9015/TASK_VERSIONING.md));
  keep the task definition with each log so it can be re-graded (tau2).
- **What to log per trial:** transcript, `exit_status`, number of turns and tool calls, tool
  errors, tokens (input, output, cache read/write), cost, latency, the submission, and the
  per-number grading detail.
- **Independent reference answers:** reference figures come from the same snapshots as the tools.
  If they come from the same code too, a snapshot-builder bug passes the eval unnoticed. Compute
  references through a separate code path where feasible and hand-check a sample.

---

## 5. Decisions this implies for P1

| # | Decision | Recommendation | Evidence |
|---|---|---|---|
| 1 | How the final answer is returned | `submit_answer` tool, `strict: true`, `tool_choice: auto`; validated in the loop; `is_error` on guardrail failure | [Inspect `_react.py` L198-210](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/agent/_react.py#L198-L210); [SWE-agent `tools.py` L109](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/tools/tools.py#L109); [Sonnet 5.5 forced tool use](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5) |
| 2 | Model ends without submitting | One or two continue nudges, then `exit_status = no_submission`, scored 0 and reported | [Inspect `_types.py` L49-51](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/agent/_types.py#L49-L51); [SWE-agent autosubmit L1076-1218](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/agent/agents.py#L1076-L1218) |
| 3 | Loop budgets | Turn cap about 10-12; `max_tokens` per call; per-question cost cap; separate cap (3) on malformed-call retries | [OpenAI `run_config.py` L45](https://github.com/openai/openai-agents-python/blob/1c1a28d/src/agents/run_config.py#L45); [MCP client `MAX_TOOL_TURNS`](https://github.com/modelcontextprotocol/quickstart-resources/blob/470d1ba/mcp-client-python/client.py#L17); [SWE-agent `models.py` L73-78](https://github.com/SWE-agent/SWE-agent/blob/3ea751c/sweagent/agent/models.py#L73-L78) |
| 4 | Stop reasons | Handle `tool_use`, `end_turn`, `max_tokens`, `refusal`, `model_context_window_exceeded`, empty responses | [Stop reasons docs](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons) |
| 5 | Thinking blocks | Append the whole `response.content` each turn; never strip thinking blocks; do not send `disabled` | [Sonnet 5.5 what's new](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5) |
| 6 | Parallel tool calls | Run all `tool_use` blocks; all results in one user message, no text after | [Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use) |
| 7 | Tool set | Keep ~7 high-level tools, verb_noun names, enum parameters | [Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents); [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) |
| 8 | Tool errors | Invalid input: `ToolError` listing valid values. Valid input, figure absent: normal result saying so. Crash: generic error | [MCP tools.mdx L738-785](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/server/tools.mdx#L738-L785); [SDK handling-errors](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/servers/handling-errors.md) |
| 9 | Output size | Default and max on `strikes_each_side`; truncation note with the next call | [SWE-agent paper §3/§5](https://arxiv.org/pdf/2405.15793v3); [fetch server L476-478](https://github.com/modelcontextprotocol/servers/blob/bbb701e/src/fetch/src/mcp_server_fetch/server.py#L476-L478) |
| 10 | Provenance | Snapshot id, tz-aware as-of, engine version, units and figure ids in every result; harness derives `sources` | [Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents); [MCP structured content L496-516](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/server/tools.mdx#L496-L516) |
| 11 | Annotations, order | `readOnlyHint: true`, `openWorldHint: false`; deterministic `tools/list` order | [schema.ts L1918-1953](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/schema/2026-07-28/schema.ts#L1918-L1953); [changelog minor 3](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5ea9960/docs/specification/2026-07-28/changelog.mdx) |
| 12 | Server tests | `Client(server)` in memory with pytest + anyio, test-first | [SDK testing docs](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/get-started/testing.md) |
| 13 | Answer schema details | All fields required, no numeric constraints, lowercase unit enum compared case-insensitively, no "reasoning" field, readable figure ids | [Structured outputs limits](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) |
| 14 | Scoring rule | +1 / 0 / -3; `cannot_answer` = +1 on unanswerable tasks; penalty stated in the system prompt (t = 0.75) | [SimpleQA paper](https://arxiv.org/abs/2411.04368); [Kalai et al. §4.2](https://arxiv.org/abs/2509.04664) |
| 15 | Numeric grading | Custom Inspect scorer: unit exact, value within per-figure tolerance at reported precision, percent canonicalised | [Inspect `_match.py` L22-30](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/scorer/_match.py#L22-L30); [TAT-QA metric](https://github.com/NExTplusplus/TAT-QA/blob/870accc/tatqa_metric.py#L145-L198); [SimpleQA grader L60-67](https://github.com/openai/simple-evals/blob/652c89d/simpleqa_eval.py#L60-L67) |
| 16 | Trials and metrics | `Epochs(5, ["mean", "pass_k_5"-style reducer])`; report SimpleQA breakdown, net score, cost per question | [Inspect reducers L163-246](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/src/inspect_ai/scorer/_reducer/reducer.py#L163-L246); [tau2 `agent_metrics.py`](https://github.com/sierra-research/tau2-bench/blob/dd8757d/src/tau2/metrics/agent_metrics.py#L113-L126) |
| 17 | Harness integration | `agent_bridge()` around the hand-written loop; `cost_limit` + `message_limit` per sample; `react()` + MCP as a baseline | [agent-bridge docs](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/agent-bridge.qmd#L31-L65); [setting-limits](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/setting-limits.qmd#L184-L203) |
| 18 | Task set | Balanced (answerable and unanswerable), `purpose` per task, held-out part, `N-X` version, re-gradable logs, independent references | [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents); [inspect_evals TASK_VERSIONING](https://github.com/UKGovernmentBEIS/inspect_evals/blob/3df9015/TASK_VERSIONING.md); [tau2 CHANGELOG](https://github.com/sierra-research/tau2-bench/blob/dd8757d/CHANGELOG.md#L20-L45) |
| 19 | Tracing | Langfuse Python SDK v4 + `opentelemetry-instrumentation-anthropic`; MCP server spans come free; propagate trace context in `_meta`; settle Cloud versus self-hosted | [Langfuse Anthropic integration](https://langfuse.com/integrations/model-providers/anthropic); [v3 to v4](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4); [SDK OTel docs](https://github.com/modelcontextprotocol/python-sdk/blob/754254c/docs/run/opentelemetry.md) |
| 20 | Ticket order | 8 split into 8a (early) and 8b; ticket 6 includes the MCP client; add HTTP transport, prompt caching, exam v2 / judge, CONTEXT.md | Section 1, Q17 verdict |

Inspect logs `pass_at(k=5)` as `pass_at_5` ([`metrics.qmd` line 128](https://github.com/UKGovernmentBEIS/inspect_ai/blob/86c1157/docs/metrics.qmd#L128)); check the logged name of `pass_k` on the first run rather than assuming it.

---

## 6. Learning resources per concept

Ranked within each concept, best first; the entries marked **start here** are the ones to read or
watch first (usually one video, one article and the official docs, but not forced to that shape).
These lists are meant to be copied into the "Concepts" heading of the matching ticket. Every link
below was opened on 2026-10-14. "Length" for articles is an estimate from word count. Paid or
login-only items say so.

### 6.1 What an agent / tool-use loop is

1. **Start here (video):** [How We Build Effective Agents](https://www.youtube.com/watch?v=D7_ipDqhtwk), Barry Zhang (Anthropic), AI Engineer Summit, 15 min, 2025-04-04. Short, from the author of the post below; covers when not to build an agent, keeping the loop simple, "thinking like your agent".
2. **Start here (article):** [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), Schluntz and Zhang (Anthropic), ~12 min, 2024-12-19 (updated 2026-08-10). Defines workflows versus agents, argues for using the API directly, has the ACI appendix.
3. **Start here (docs):** [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works), [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), [Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use), [Stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons), Anthropic, current. The exact contract the loop must follow.
4. [Tutorial: Build a tool-using agent](https://platform.claude.com/docs/en/agents-and-tools/tool-use/build-a-tool-using-agent), Anthropic docs, ~15 min, current. Builds the loop in "rings". Warning: its loop has no turn cap; add one.
5. [Build an MCP client](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-client) and its [code](https://github.com/modelcontextprotocol/quickstart-resources/tree/main/mcp-client-python), MCP project, for SDK 2.x, updated 2026-09-20. The loop plus the MCP client side, with `MAX_TOOL_TURNS`; the nearest thing to ticket 6.
6. [How to Build an Agent](https://ampcode.com/notes/how-to-build-an-agent), Thorsten Ball (Amp), ~25 min, 2025-04-15. Shows that a working agent is a short loop plus tools. Warning: written in Go with 2025 model names; read for the idea.
7. [Designing agentic loops](https://simonwillison.net/2025/Sep/30/designing-agentic-loops/), Simon Willison, ~8 min, 2025-09-30. When a loop is worth it ("clear success criteria" plus trial and error) and budget-limited credentials.
8. [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), Anthropic, ~13 min, 2025-09-29. Covers the roadmap's "context engineering" concept.
9. [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), Anthropic docs, current. The P1 prompt-caching concept; relevant because tools and the system prompt repeat every turn.
10. [Building with the Claude API](https://anthropic.skilljar.com/claude-with-the-anthropic-api), Anthropic Academy, free course (67 lessons; free account). Broad; parts are older than Sonnet 5.5 (forced tool choice and thinking settings changed), so check against the docs above.

### 6.2 Tool design

1. **Start here (article):** [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents), Ken Aizawa et al. (Anthropic), ~15 min, 2025-09-11. The main reference for Q15.
2. **Start here (docs):** [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) and [Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use), Anthropic, current. Good and bad description examples; `input_examples`; forced-tool restrictions.
3. **Start here (video):** no talk dedicated to tool design was verified; the "Thinking like your agent" segment (8:01) of Barry Zhang's talk above is the closest.
4. [SWE-agent paper](https://arxiv.org/abs/2405.15793), Yang et al., research paper, 2024 (v3 2024-11-11). Read §2 and §5.1 for measured ACI effects.
5. [Tool evaluation cookbook](https://platform.claude.com/cookbook/tool-evaluation-tool-evaluation), Anthropic, notebook, current. A minimal harness for testing tool descriptions. Warning: uncapped loop, first-tool-only handling (section 2.1).

### 6.3 MCP (protocol, servers, transports, Python SDK)

1. **Start here (docs):** [MCP specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) (tools page) and [Build an MCP server](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server) (requires Python SDK ≥ 2.0), MCP project, 2026-07-28.
2. **Start here (article):** [The 2026-07-28 Specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/), MCP blog, ~10 min, 2026-07-28. What changed and why (no handshake, no sessions, explicit handles), with the [release-candidate post](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) for the longer reasoning.
3. **Start here (video):** [Why Agents Need Connectivity, Not Better Models](https://www.youtube.com/watch?v=3LwylP2as8A), David Soria Parra (MCP co-creator), Agentic AI Foundation channel, 13 min, 2026-10-04. Current; covers making MCP stateless (from 7:40).
4. [MCP Python SDK docs](https://py.sdk.modelcontextprotocol.io/), especially [What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/), [Testing](https://py.sdk.modelcontextprotocol.io/get-started/testing/), [Handling errors](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/), [Structured output](https://py.sdk.modelcontextprotocol.io/servers/structured-output/), current (v2.3.0). The pages tickets 4 and 5 need.
5. [MCP Inspector](https://github.com/modelcontextprotocol/inspector), MCP project, tool. Click-through testing of a server.
6. [stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio), spec page, short. Why stray `print()` breaks the server.
7. [The Future of MCP](https://www.youtube.com/watch?v=v3Fr2JR47KA), David Soria Parra, AI Engineer, 19 min, 2026-04-19. Warning: three months before the final spec; direction, not details.
8. [Introduction to Model Context Protocol](https://anthropic.skilljar.com/introduction-to-model-context-protocol), Anthropic Academy, free course. Warning: from mid-2025, before the stateless revision and SDK v2 (`FastMCP`, `initialize`); useful only for concepts (tools versus resources versus prompts).
9. [Learn MCP Servers with Python (EASY)](https://www.youtube.com/watch?v=Ek8JHgZtmcI), Alejandro AO, 39 min, 2025-03-12. Warning: v1 SDK and `FastMCP`; outdated for code.
10. Avoid `modelcontextprotocol.info`: an unofficial mirror that still shows SDK 1.2 and `FastMCP`.

### 6.4 Structured outputs

1. **Start here (docs):** [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), Anthropic, current. JSON outputs, strict tools, combining both, schema limits, enum casing, refusals.
2. **Start here (video course):** [Getting Structured LLM Output](https://www.deeplearning.ai/courses/getting-structured-llm-output), DeepLearning.AI with .txt, taught by Will Kurt and Cameron Pfiffer, short course (free), 2025-04-02. Explains constrained decoding (how logits are masked). Warning: uses OpenAI and open models, not the Claude API.
3. **Start here (article):** no standalone article was verified; the Anthropic page above plus the [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) (OpenAI docs, current) give two vendors' view of the same idea.
4. [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/), Pydantic docs, current. The models behind tool return types and the answer schema.
5. [Understanding JSON Schema](https://json-schema.org/understanding-json-schema/about), json-schema.org, free online book. Reference for `enum`, `required`, `additionalProperties`.

### 6.5 Agent evals (graders, pass^k, LLM judges, error analysis)

1. **Start here (article):** [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), Anthropic, ~25 min, 2026-01-09. Vocabulary, grader types, pass@k versus pass^k, step-by-step roadmap.
2. **Start here (video):** [Error Analysis: The Highest ROI Technique In AI Engineering](https://www.youtube.com/watch?v=e2i6JbU2R-s), Hamel Husain, 12 min, 2025-03-24. How to read traces and turn failures into categories before writing graders.
3. **Start here (docs):** the Inspect [Scorers](https://inspect.aisi.org.uk/scorers.html) and [Metrics / reducing epochs](https://inspect.aisi.org.uk/metrics.html) pages (see 6.6).
4. [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/), Hamel Husain, ~17 min, 2024-03-29. The original three-level framework (unit tests, human and model eval, A/B).
5. [A Field Guide to Rapidly Improving AI Products](https://hamel.dev/blog/posts/field-guide/), Hamel Husain, ~25 min, 2025-03-24. Data viewers, error analysis, binary pass/fail judgements.
6. [Using LLM-as-a-Judge For Evaluation: A Complete Guide](https://hamel.dev/blog/posts/llm-judge/), Hamel Husain, ~30 min, 2024-10-29. For the later prose-contradiction judge.
7. [Why AI evals are the hottest new skill for product builders](https://www.youtube.com/watch?v=BsWxPI9UM4c), Lenny's Podcast with Hamel Husain and Shreya Shankar, 1 h 47 min, 2025-09-25. Long; the error-analysis and judge-validation segments (16:51 to 1:00:51) are the useful part.
8. [AI Evals: Everything You Need to Know](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain, reference FAQ (very long), updated 2026-09-18. Look things up, do not read end to end.
9. [τ-bench paper](https://arxiv.org/abs/2406.12045) (Yao et al., 2024) and [Sierra blog](https://sierra.ai/blog/benchmarking-ai-agents). Where pass^k comes from.
10. [SimpleQA paper](https://arxiv.org/abs/2411.04368) (OpenAI, 2024) and [Why Language Models Hallucinate](https://arxiv.org/abs/2509.04664) (Kalai et al., 2025, §4.2). The scoring rule behind negative marking.
11. [Evaluating the Effectiveness of LLM-Evaluators](https://eugeneyan.com/writing/llm-evaluators/), Eugene Yan, long survey (~40 min), 2024. Read later, if a judge is added.
12. [AI Evals for Engineers & PMs](https://maven.com/parlance-labs/evals), Hamel Husain and Shreya Shankar, paid cohort course (Maven). Listed for completeness; not needed for P1.

### 6.6 Inspect AI

1. **Start here (docs):** [Tutorial](https://inspect.aisi.org.uk/tutorial.html), then [Datasets](https://inspect.aisi.org.uk/datasets.html), [Custom scorers](https://inspect.aisi.org.uk/custom-scorers.html), [Metrics (reducing epochs)](https://inspect.aisi.org.uk/metrics.html), [Setting limits](https://inspect.aisi.org.uk/setting-limits.html), [Agent bridge](https://inspect.aisi.org.uk/agent-bridge.html), [Log viewer](https://inspect.aisi.org.uk/log-viewer.html), UK AISI, current (0.3.280).
2. **Start here (video):** [Inspect - A LLM Eval Framework Used by Anthropic, DeepMind, Grok and More](https://www.youtube.com/watch?v=_UY49Q_qFhs), J.J. Allaire (Inspect lead) on Hamel Husain's channel, 43 min, 2025-06-21. Includes the agent bridge (17:26) and logging tools.
3. **Start here (article / worked example):** the [SimpleQA port in inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/simpleqa), UK AISI and contributors, code, current. A real task with a dict-valued score and a custom metric, close to what ticket 8 needs.
4. [Inspect, an OSS Framework for LLM Evals](https://www.youtube.com/watch?v=kNaZU9bz-UM), J.J. Allaire, 47 min, 2024-07-09. Warning: 2024, before `react()`, `agent_bridge()` and the current agent API.

### 6.7 OpenTelemetry tracing and Langfuse

1. **Start here (docs):** [OpenTelemetry Python getting started](https://opentelemetry.io/docs/languages/python/getting-started/) and [Traces concepts](https://opentelemetry.io/docs/concepts/signals/traces/), OpenTelemetry, current. Spans, traces, exporters in plain terms.
2. **Start here (docs):** [Langfuse get started](https://langfuse.com/docs/observability/get-started), [Anthropic integration](https://langfuse.com/integrations/model-providers/anthropic) (uses `opentelemetry-instrumentation-anthropic`), [OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry), Langfuse, current (Python SDK 4.17.0, 2026-10-05).
3. **Start here (video):** [Making GenAI Observable with OpenTelemetry](https://www.youtube.com/watch?v=RNaa_48LWBY), channel "wiggitywhitney", 16 min, 2026-01-15. Recent walk-through of GenAI traces. Not reviewed beyond its description and length.
4. **Article:** [Inside the LLM Call: GenAI Observability with OpenTelemetry](https://opentelemetry.io/blog/2026/genai-observability/), OpenTelemetry blog, ~5 min, 2026-05-14.
5. [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/), OpenTelemetry spec, current; status is still "Development", so attribute names can change.
6. [MCP SDK OpenTelemetry page](https://py.sdk.modelcontextprotocol.io/run/opentelemetry/), current. The server already emits spans.
7. [Langfuse Python v3 to v4 upgrade guide](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4), updated 2026-09-14. Read this before following any older Langfuse example: v4 renamed `start_span`/`start_generation` to `start_observation`, split `update_current_trace`, and filters non-LLM spans by default.
8. [Langfuse Launch Week 3, Day 5: OpenTelemetry Python SDK](https://www.youtube.com/watch?v=md_TKMmNz28), Langfuse, 2.5 min, 2025-05-23. Warning: shows the v3 API.

### 6.8 Test-driven development in Python with pytest

1. **Start here (article):** [Canon TDD](https://tidyfirst.substack.com/p/canon-tdd), Kent Beck, ~6 min, 2023-12-11. The red-green-refactor loop, stated by its originator, including "write a list of test scenarios" first.
2. **Start here (docs):** [pytest: Get started](https://docs.pytest.org/en/stable/getting-started.html), [fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html), [parametrize](https://docs.pytest.org/en/stable/how-to/parametrize.html), plus [AnyIO testing](https://anyio.readthedocs.io/en/stable/testing.html) for async tests (the MCP SDK's test pattern uses it) and the [MCP SDK Testing page](https://py.sdk.modelcontextprotocol.io/get-started/testing/).
3. **Start here (video):** no pytest video was verified for this pass. [Hynek Schlawack's project-layout video](https://www.youtube.com/watch?v=mFyE9xgeKcA) (6.9) covers where tests live in a uv project.
4. [Obey the Testing Goat](https://www.obeythetestinggoat.com/), Harry Percival, free online book (O'Reilly, third edition with a preface on "TDD in the age of AI"). The best long-form TDD teaching; warning: built around a Django web app, so use it for the habit, not the stack.
5. [pytest Tutorial: Effective Python Testing](https://realpython.com/pytest-python-testing/), Real Python, ~30 min, published 2024-12-08, updated 2026-10-03.

### 6.9 `uv` project setup

1. **Start here (docs):** [Working on projects](https://docs.astral.sh/uv/guides/projects/) and [Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/), Astral, current.
2. **Start here (video):** [Python Tutorial: UV](https://www.youtube.com/watch?v=AMdG7IjgSPM), Corey Schafer, 27 min, 2025-04-30. Clear beginner walk-through of `uv init`, `uv add`, `uv run`, `uv sync`.
3. **Start here (article):** the docs above are the article; no separate article was verified.
4. [My 2025 uv-based Python Project Layout for Production Apps](https://www.youtube.com/watch?v=mFyE9xgeKcA), Hynek Schlawack, 24 min, 2025-02-24. `src/` layout, dev dependencies, tests.
5. [uv: An Extremely Fast Python Package Manager](https://www.youtube.com/watch?v=gSKTfG1GXYQ), Charlie Marsh (uv author), Jane Street talk, 41 min, 2024-10-23. Why it is fast; optional.

---

## 7. Sources, with versions and dates

**Repositories read (commit, commit date)**

| Repo | Commit | Date | Version |
|---|---|---|---|
| [anthropics/claude-cookbooks](https://github.com/anthropics/claude-cookbooks/tree/39cd5a7) | `39cd5a7` | 2026-10-13 | n/a |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python/tree/1c1a28d) | `1c1a28d` | 2026-10-14 | 0.23.1 |
| [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent/tree/3ea751c) | `3ea751c` | 2026-07-16 | 1.1.0 |
| [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai/tree/86c1157) | `86c1157` | 2026-10-14 | 0.3.280 |
| [UKGovernmentBEIS/inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/3df9015) | `3df9015` | 2026-10-14 | simpleqa task 5-D |
| [modelcontextprotocol/modelcontextprotocol](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/5ea9960) | `5ea9960` | 2026-10-13 | spec 2026-07-28 |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/tree/754254c) | `754254c` | 2026-10-13 | latest release v2.3.0 (2026-10-02) |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers/tree/bbb701e) | `bbb701e` | 2026-10-11 | pins SDK v1 |
| [modelcontextprotocol/quickstart-resources](https://github.com/modelcontextprotocol/quickstart-resources/blob/470d1ba/mcp-client-python/client.py) | `470d1ba` | 2026-09-20 | client.py only |
| [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench/tree/dd8757d) | `dd8757d` | 2026-10-13 | 1.0.1 |
| [openai/simple-evals](https://github.com/openai/simple-evals/tree/652c89d) | `652c89d` | 2026-04-22 | not updated since 2025-07 |
| [czyssrs/FinQA](https://github.com/czyssrs/FinQA/tree/0f16e28) | `0f16e28` | 2022-06-05 | n/a |
| [NExTplusplus/TAT-QA](https://github.com/NExTplusplus/TAT-QA/tree/870accc) | `870accc` | 2024-12-09 | n/a |

**Docs and specs (read 2026-10-14; living pages without version numbers)**

- Anthropic: [Tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview), [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works), [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools), [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), [Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use), [Tutorial: build a tool-using agent](https://platform.claude.com/docs/en/agents-and-tools/tool-use/build-a-tool-using-agent), [Stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons), [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [What's new in Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5).
- MCP: [spec 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) (read from the repo above), [release post](https://blog.modelcontextprotocol.io/posts/2026-07-28/) (2026-07-28), [RC post](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/), [Build an MCP server / client](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-client).
- Inspect AI docs at [inspect.aisi.org.uk](https://inspect.aisi.org.uk/) (read from the repo `docs/` folder at `86c1157`).
- Langfuse: [Anthropic integration](https://langfuse.com/integrations/model-providers/anthropic), [Python v3 to v4](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4) (updated 2026-09-14), [PyPI langfuse 4.17.0](https://pypi.org/project/langfuse/) (2026-10-05).

**Engineering posts and papers**

- Anthropic, [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), 2024-12-19 (modified 2026-08-10).
- Anthropic, [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents), 2025-09-11 (modified 2026-01-06).
- Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), 2026-01-09 (modified 2026-03-18).
- Yang et al., [SWE-agent](https://arxiv.org/abs/2405.15793), arXiv 2405.15793 v3, 2024-11-11.
- Yao et al., [τ-bench](https://arxiv.org/abs/2406.12045), arXiv 2406.12045, 2024; Barres et al., [τ²-bench](https://arxiv.org/abs/2506.07982), arXiv 2506.07982, 2025.
- Wei et al. (OpenAI), [SimpleQA](https://arxiv.org/abs/2411.04368), arXiv 2411.04368, 2024.
- Kalai, Nachum, Vempala, Zhang, [Why Language Models Hallucinate](https://arxiv.org/abs/2509.04664), arXiv 2509.04664, 2025 (§4.2).
- Vals AI, [Finance Agent Benchmark](https://arxiv.org/abs/2508.00828), arXiv 2508.00828, 2025.
- Chen et al., [FinQA](https://github.com/czyssrs/FinQA) (EMNLP 2021) and Zhu et al., [TAT-QA](https://github.com/NExTplusplus/TAT-QA) (ACL 2021): official eval scripts only.

**Not reached or not verified**

- The SWE-agent and Vals papers were read through a PDF-to-text extraction; a few numbers in the
  extraction were garbled (the SWE-agent headline counts, the Vals dataset totals). Figures quoted
  above are the ones that read cleanly; check the PDFs before quoting them elsewhere.
- The `inspect_evals` shallow clone failed to check out on Windows; its files were read from the
  git object store at the same commit instead.
- No dedicated video on tool design, structured outputs from Anthropic, or pytest was verified, so
  none is listed for those slots.
- The roadmap and the P1 plan disagree on Langfuse Cloud versus self-hosted (section 1, Q17 item 5).
