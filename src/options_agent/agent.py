import asyncio
import ssl
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, get_args

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from options_agent.grader import Submission
from options_agent.server import Unit

MODEL = "claude-sonnet-5-5"

# Claude Sonnet 5.5 prices, dollars per million tokens.
PRICE_INPUT = 2.00
PRICE_OUTPUT = 10.00
PRICE_CACHE_WRITE = 2.50
PRICE_CACHE_READ = 0.20

SYSTEM_PROMPT = """You answer questions about S&P 500 index options (SPXW) on a few frozen \
trading days. Every question is about 15:45 New York time on its day.

Use the tools to get every number; never estimate, compute or convert one yourself. Give each \
number exactly as a tool returned it, with that tool's unit and figure id.

Finish only by calling submit_answer. A correct answer earns 1 point, cannot_answer earns 0 and \
a wrong answer costs 3 points, so answer only if you are more than 75% sure. If a tool says a \
figure is missing, or the day is not in list_dates, submit cannot_answer and list what is \
missing in missing_data."""

SUBMIT_ANSWER = {
    "name": "submit_answer",
    "description": (
        "Submit your final answer; this is the only way to finish. status is answered or "
        "cannot_answer. answer is the answer in prose. numbers lists every number in the "
        "answer, each exactly as a tool returned it, with its unit and figure id. missing_data "
        "lists the data you would need but no tool has; it must not be empty for cannot_answer."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["answered", "cannot_answer"]},
            "answer": {"type": "string"},
            "numbers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "number"},
                        "unit": {"type": "string", "enum": list(get_args(Unit))},
                        "figure_id": {"type": "string"},
                    },
                    "required": ["name", "value", "unit", "figure_id"],
                    "additionalProperties": False,
                },
            },
            "missing_data": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "answer", "numbers", "missing_data"],
        "additionalProperties": False,
    },
}

# Inspect's react() continue message, adapted (docs/research/p1-references.md section 2.4).
NUDGE = (
    "Please proceed to the next step using your best judgement. If you believe you have "
    "completed the task, call the submit_answer tool with your final answer."
)
MAX_NUDGES = 2

SERVER = StdioServerParameters(command="uv", args=["run", "mcp-server"])

Stop = Literal[
    "submitted",
    "no_submission",
    "refused",
    "max_tokens",
    "out_of_turns",
    "out_of_tokens",
    "out_of_money",
    "unexpected_stop",
]


@dataclass(frozen=True)
class Budget:
    turns: int = 12
    tokens: int = 300_000
    dollars: float = 0.50


@dataclass
class Spend:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0

    @property
    def tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    @property
    def dollars(self) -> float:
        return (
            self.input_tokens * PRICE_INPUT
            + self.output_tokens * PRICE_OUTPUT
            + self.cache_write_tokens * PRICE_CACHE_WRITE
            + self.cache_read_tokens * PRICE_CACHE_READ
        ) / 1_000_000


DEFAULT_BUDGET = Budget()


@dataclass
class Outcome:
    stop: Stop
    submission: Submission | None
    sources: list[dict]
    turns: int
    spend: Spend
    messages: list = field(repr=False)


async def list_tools(mcp: Client) -> list[dict]:
    """The MCP server's tools as Messages API tool definitions, in the server's order."""
    result = await mcp.list_tools()
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in result.tools
    ]


async def run_tool(mcp: Client, call: Any, seen: dict[str, dict]) -> dict:
    """Call one tool, remember the figures it returned, and make its tool_result block."""
    result = await mcp.call_tool(call.name, call.input)
    record_figures(result.structured_content, seen)
    text = "\n".join(block.text for block in result.content if block.type == "text")
    return {
        "type": "tool_result",
        "tool_use_id": call.id,
        "content": text,
        "is_error": result.is_error,
    }


def record_figures(content: dict | None, seen: dict[str, dict]) -> None:
    """Remember every figure in a tool result, with the snapshot it came from."""
    for figure in (content or {}).get("figures", []):
        seen[figure["id"]] = {
            "value": figure["value"],
            "unit": figure["unit"],
            "source": {key: content[key] for key in ("snapshot", "as_of", "engine_commit")},
        }


def same_at_precision(submitted: float, returned: float) -> bool:
    """True if the returned value rounds to the submitted one at the submitted decimals."""
    decimals = max(0, -Decimal(str(submitted)).as_tuple().exponent)
    return abs(returned - submitted) <= 0.5 * 10.0**-decimals + 1e-12


def schema_problems(error: ValidationError) -> list[str]:
    """Each place a submission breaks the submit_answer schema, one line each."""
    return [f"{'.'.join(map(str, e['loc']))}: {e['msg']}." for e in error.errors()]


def check_submission(submission: Submission, seen: dict[str, dict]) -> list[str]:
    """Every guardrail the submission fails; an empty list means it is accepted."""
    problems = []
    if submission.status == "cannot_answer" and not submission.missing_data:
        problems.append("cannot_answer needs missing_data to say what is missing.")
    for number in submission.numbers:
        figure = seen.get(number.figure_id)
        if figure is None:
            problems.append(f"{number.figure_id} is not a figure any tool returned in this run.")
        elif number.unit.lower() != figure["unit"].lower():
            problems.append(f"{number.figure_id} is in {figure['unit']}, not {number.unit}.")
        elif not same_at_precision(number.value, figure["value"]):
            problems.append(f"{number.figure_id} is {figure['value']}, not {number.value}.")
    return problems


def sources_for(submission: Submission, seen: dict[str, dict]) -> list[dict]:
    """The snapshots behind the cited figures, each once, in the order first cited."""
    sources: list[dict] = []
    for number in submission.numbers:
        source = seen[number.figure_id]["source"]
        if source not in sources:
            sources.append(source)
    return sources


def check_stop(response: Any) -> Stop | None:
    """Why the run ends on this reply's stop reason, or None to carry on."""
    if response.stop_reason == "refusal":
        return "refused"
    if response.stop_reason == "max_tokens":
        return "max_tokens"
    if response.stop_reason not in ("tool_use", "end_turn"):
        return "unexpected_stop"
    return None


def check_budget(spend: Spend, budget: Budget) -> Stop | None:
    """Which budget is used up, or None if there is room for another call."""
    if spend.tokens > budget.tokens:
        return "out_of_tokens"
    if spend.dollars > budget.dollars:
        return "out_of_money"
    return None


async def run_agent(
    question: str,
    *,
    claude: AsyncAnthropic,
    mcp: Client,
    budget: Budget = DEFAULT_BUDGET,
    model: str = MODEL,
) -> Outcome:
    """Question in, outcome out: loop until Claude submits an answer or the run must stop."""
    tools = [*await list_tools(mcp), SUBMIT_ANSWER]
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    messages: list = [{"role": "user", "content": question}]
    spend = Spend()
    seen: dict[str, dict] = {}
    nudges = 0

    for turns in range(1, budget.turns + 1):
        response = await claude.messages.create(
            model=model,
            max_tokens=16_000,
            output_config={"effort": "medium"},
            system=system,
            tools=tools,
            messages=messages,
        )
        spend.add(response.usage)
        messages.append({"role": "assistant", "content": response.content})

        stop = check_stop(response)
        if stop is not None:
            return Outcome(stop, None, [], turns, spend, messages)

        if response.stop_reason == "end_turn":
            if nudges == MAX_NUDGES:
                return Outcome("no_submission", None, [], turns, spend, messages)
            nudges += 1
            reply: str | list = NUDGE
        else:
            calls = [block for block in response.content if block.type == "tool_use"]
            tool_calls = [call for call in calls if call.name != "submit_answer"]
            reply = await asyncio.gather(*(run_tool(mcp, call, seen) for call in tool_calls))
            for call in calls:
                if call.name != "submit_answer":
                    continue
                try:
                    submission = Submission.model_validate(call.input)
                except ValidationError as error:
                    problems = schema_problems(error)
                else:
                    problems = check_submission(submission, seen)
                if not problems:
                    sources = sources_for(submission, seen)
                    return Outcome("submitted", submission, sources, turns, spend, messages)
                rejection = "Submission rejected: " + " ".join(problems)
                reply.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": rejection,
                        "is_error": True,
                    }
                )

        stop = check_budget(spend, budget)
        if stop is not None:
            return Outcome(stop, None, [], turns, spend, messages)
        messages.append({"role": "user", "content": reply})

    return Outcome("out_of_turns", None, [], budget.turns, spend, messages)


async def ask(
    question: str, *, claude: AsyncAnthropic, server: StdioServerParameters = SERVER
) -> Outcome:
    """Start the MCP server over stdio, answer one question, and stop the server."""
    async with Client(server) as mcp:
        return await run_agent(question, claude=claude, mcp=mcp)


def main() -> None:
    """Answer the question given on the command line: uv run ask "..."."""
    question = " ".join(sys.argv[1:])
    # databento's pip-system-certs patches ssl on Windows, which sends httpx2's own
    # truststore context into endless recursion; a context from ssl itself works.
    http_client = DefaultAsyncHttpxClient(verify=ssl.create_default_context())
    outcome = asyncio.run(ask(question, claude=AsyncAnthropic(http_client=http_client)))
    spend = outcome.spend
    if outcome.submission is not None:
        print(outcome.submission.model_dump_json(indent=2))
        print(f"sources: {outcome.sources}")
    print(f"\n{outcome.stop} after {outcome.turns} turns, ${spend.dollars:.4f}")
    print(
        f"tokens: {spend.input_tokens} in, {spend.output_tokens} out, "
        f"{spend.cache_write_tokens} cache write, {spend.cache_read_tokens} cache read"
    )
