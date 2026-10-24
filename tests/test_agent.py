import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage
from mcp import Client, StdioServerParameters

from options_agent.agent import (
    NUDGE,
    SUBMIT_ANSWER,
    SYSTEM_PROMPT,
    Budget,
    Spend,
    ask,
    run_agent,
    same_at_precision,
)
from options_agent.server import build_server

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"


class FakeMessages:
    """Stands in for claude.messages: replays scripted replies and records every request."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return self.replies.pop(0)


def fake_claude(*replies):
    return SimpleNamespace(messages=FakeMessages(replies))


def reply(stop_reason, *content, usage=None):
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5-5",
        content=list(content),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=usage or Usage(input_tokens=100, output_tokens=20),
    )


def call(id, name, **input):
    return ToolUseBlock(type="tool_use", id=id, name=name, input=input)


def submit(status="answered", answer="One day.", numbers=(), missing_data=(), usage=None):
    submission = call(
        "toolu_9",
        "submit_answer",
        status=status,
        answer=answer,
        numbers=list(numbers),
        missing_data=list(missing_data),
    )
    return reply("tool_use", submission, usage=usage)


def number(figure_id, value, unit):
    return {"name": "figure", "value": value, "unit": unit, "figure_id": figure_id}


ATM_IV = "skew:2025-11-20:2025-11-20:atm_iv"
SOURCE = {
    "snapshot": "2025-11-20.json",
    "as_of": "2025-11-20T15:45:00-05:00",
    "engine_commit": "345539eaef2caee1fd94d773d2eefe71de33ac9a",
}


async def test_a_tool_call_then_a_submission_runs_the_tool_and_returns_it():
    claude = fake_claude(
        reply("tool_use", ToolUseBlock(type="tool_use", id="toolu_1", name="list_dates", input={})),
        submit(),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days can you answer about?", claude=claude, mcp=mcp)

    assert outcome.stop == "submitted"
    assert outcome.submission.answer == "One day."
    assert outcome.turns == 2
    first, second = claude.messages.requests
    assert [tool["name"] for tool in first["tools"]] == [
        "list_dates",
        "list_expiries",
        "get_chain",
        "get_skew",
        "get_realised_vol",
        "get_implied_move",
        "get_gamma_exposure",
        "submit_answer",
    ]
    result = second["messages"][-1]["content"][0]
    assert result["tool_use_id"] == "toolu_1"
    assert result["is_error"] is False
    assert json.loads(result["content"])["dates"][0]["date"] == "2025-11-20"


async def test_parallel_tool_calls_go_back_together_in_one_message_in_call_order():
    claude = fake_claude(
        reply(
            "tool_use",
            call("toolu_1", "list_dates"),
            call("toolu_2", "list_expiries", date="2025-11-20"),
        ),
        submit(),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        await run_agent("Which days and expiries?", claude=claude, mcp=mcp)

    question, assistant, tool_results = claude.messages.requests[1]["messages"]
    assert tool_results["role"] == "user"
    assert [result["tool_use_id"] for result in tool_results["content"]] == ["toolu_1", "toolu_2"]
    assert [result["is_error"] for result in tool_results["content"]] == [False, False]


async def test_a_tool_error_goes_back_to_claude_marked_as_an_error():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "get_skew", date="2025-11-21", expiry="2025-11-21")),
        submit(),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("What is the skew on 2025-11-21?", claude=claude, mcp=mcp)

    assert outcome.stop == "submitted"
    result = claude.messages.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert result["content"] == (
        "Error executing tool get_skew: "
        "No snapshot for date 2025-11-21. Available dates: 2025-11-20."
    )


async def test_thinking_blocks_go_back_to_claude_unchanged():
    thinking = ThinkingBlock(type="thinking", thinking="", signature="sig-from-the-api")
    first = reply("tool_use", thinking, call("toolu_1", "list_dates"))
    claude = fake_claude(first, submit())
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        await run_agent("Which days?", claude=claude, mcp=mcp)

    assistant = claude.messages.requests[1]["messages"][1]
    assert assistant == {"role": "assistant", "content": first.content}
    assert assistant["content"][0] is thinking


@pytest.mark.parametrize(
    ("budget", "stop"),
    [
        (Budget(turns=1), "out_of_turns"),
        (Budget(tokens=50), "out_of_tokens"),
        (Budget(dollars=0.0001), "out_of_money"),
    ],
)
async def test_the_loop_stops_when_a_budget_runs_out(budget, stop):
    claude = fake_claude(*[reply("tool_use", call("toolu_1", "list_dates"))] * 3)
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp, budget=budget)

    assert outcome.stop == stop
    assert outcome.turns == 1
    assert len(claude.messages.requests) == 1


@pytest.mark.parametrize(
    ("stop_reason", "stop"),
    [("refusal", "refused"), ("max_tokens", "max_tokens"), ("pause_turn", "unexpected_stop")],
)
async def test_a_stop_reason_other_than_tool_use_or_end_turn_ends_the_run(stop_reason, stop):
    claude = fake_claude(reply(stop_reason, TextBlock(type="text", text="Partial")))
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp)

    assert outcome.stop == stop
    assert outcome.submission is None
    assert outcome.turns == 1


async def test_spend_adds_up_the_usage_of_every_turn_and_prices_it():
    claude = fake_claude(
        reply(
            "tool_use",
            call("toolu_1", "list_dates"),
            usage=Usage(input_tokens=1_000, output_tokens=200, cache_creation_input_tokens=3_000),
        ),
        submit(usage=Usage(input_tokens=500, output_tokens=100, cache_read_input_tokens=3_000)),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp)

    assert outcome.spend == Spend(
        input_tokens=1_500, output_tokens=300, cache_read_tokens=3_000, cache_write_tokens=3_000
    )
    assert outcome.spend.tokens == 7_800
    assert outcome.spend.dollars == pytest.approx(0.0141)


async def test_the_tool_list_and_system_prompt_are_cached_and_the_same_every_turn():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "list_dates")),
        submit(),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        await run_agent("Which days?", claude=claude, mcp=mcp)

    first, second = claude.messages.requests
    assert first["system"] == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert second["system"] == first["system"]
    assert second["tools"] == first["tools"]


async def test_ask_starts_the_mcp_server_over_stdio_and_submits():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "list_dates")),
        submit(),
    )
    server = StdioServerParameters(command="uv", args=["run", "mcp-server", str(FIXTURES)])

    outcome = await ask("Which days?", claude=claude, server=server)

    assert outcome.stop == "submitted"
    result = claude.messages.requests[1]["messages"][-1]["content"][0]
    assert json.loads(result["content"])["dates"][0]["date"] == "2025-11-20"


def test_submit_answer_follows_the_api_schema_limits():
    def objects(schema):
        if schema["type"] == "object":
            yield schema
            for child in schema["properties"].values():
                yield from objects(child)
        if schema["type"] == "array":
            yield from objects(schema["items"])

    schema = SUBMIT_ANSWER["input_schema"]
    assert SUBMIT_ANSWER["strict"] is True
    for obj in objects(schema):
        assert obj["required"] == list(obj["properties"])
        assert obj["additionalProperties"] is False
    text = json.dumps(schema)
    for banned in ["minimum", "maximum", "minLength", "maxLength", "reasoning"]:
        assert banned not in text


async def test_stopping_without_submitting_is_nudged_twice_then_recorded_as_no_submission():
    claude = fake_claude(*[reply("end_turn", TextBlock(type="text", text="One day."))] * 3)
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp)

    assert outcome.stop == "no_submission"
    assert outcome.turns == 3
    assert [request["messages"][-1] for request in claude.messages.requests[1:]] == [
        {"role": "user", "content": NUDGE},
        {"role": "user", "content": NUDGE},
    ]


async def test_a_nudge_then_a_submission_is_accepted():
    claude = fake_claude(reply("end_turn", TextBlock(type="text", text="One day.")), submit())
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp)

    assert outcome.stop == "submitted"
    assert outcome.turns == 2


async def test_a_valid_submission_ends_the_run_with_its_sources():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "get_skew", date="2025-11-20", expiry="2025-11-20")),
        submit(answer="ATM IV is 0.2415.", numbers=[number(ATM_IV, 0.2415, "decimal_vol")]),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("What is the ATM IV?", claude=claude, mcp=mcp)

    assert outcome.stop == "submitted"
    assert outcome.submission.numbers[0].value == 0.2415
    assert outcome.sources == [SOURCE]


async def test_an_invented_number_is_rejected_then_fixed():
    claude = fake_claude(
        submit(answer="ATM IV is 0.2415.", numbers=[number(ATM_IV, 0.2415, "decimal_vol")]),
        reply("tool_use", call("toolu_1", "get_skew", date="2025-11-20", expiry="2025-11-20")),
        submit(answer="ATM IV is 0.2415.", numbers=[number(ATM_IV, 0.2415, "decimal_vol")]),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("What is the ATM IV?", claude=claude, mcp=mcp)

    rejection = claude.messages.requests[1]["messages"][-1]["content"][0]
    assert rejection["is_error"] is True
    assert rejection["content"] == (
        f"Submission rejected: {ATM_IV} is not a figure any tool returned in this run."
    )
    assert outcome.stop == "submitted"
    assert outcome.turns == 3


@pytest.mark.parametrize(
    ("value", "unit", "problem"),
    [
        (24.15, "vol_points", f"{ATM_IV} is in decimal_vol, not vol_points."),
        (0.25, "decimal_vol", f"{ATM_IV} is 0.2415, not 0.25."),
    ],
)
async def test_a_wrong_unit_or_value_is_rejected(value, unit, problem):
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "get_skew", date="2025-11-20", expiry="2025-11-20")),
        submit(answer="ATM IV.", numbers=[number(ATM_IV, value, unit)]),
        submit(answer="ATM IV is 0.2415.", numbers=[number(ATM_IV, 0.2415, "decimal_vol")]),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("What is the ATM IV?", claude=claude, mcp=mcp)

    rejection = claude.messages.requests[2]["messages"][-1]["content"][0]
    assert rejection["content"] == f"Submission rejected: {problem}"
    assert outcome.stop == "submitted"


@pytest.mark.parametrize(
    ("submitted", "returned", "same"),
    [(-0.803, -0.8026516, True), (0.24, 0.2415, True), (0.25, 0.2415, False), (15.0, 15.6, False)],
)
def test_same_at_precision_rounds_to_the_submitted_decimals(submitted, returned, same):
    assert same_at_precision(submitted, returned) is same


async def test_cannot_answer_is_accepted_only_with_missing_data():
    claude = fake_claude(
        submit(status="cannot_answer", answer="No snapshot for that day."),
        submit(
            status="cannot_answer",
            answer="No snapshot for that day.",
            missing_data=["a snapshot for 2025-11-21"],
        ),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("What was the skew on 2025-11-21?", claude=claude, mcp=mcp)

    rejection = claude.messages.requests[1]["messages"][-1]["content"][0]
    assert rejection["content"] == (
        "Submission rejected: cannot_answer needs missing_data to say what is missing."
    )
    assert outcome.stop == "submitted"
    assert outcome.submission.status == "cannot_answer"
    assert outcome.sources == []


def test_the_instructions_state_the_marking_rule_and_forbid_conversions():
    assert "a wrong answer costs 3 points" in SYSTEM_PROMPT
    assert "more than 75% sure" in SYSTEM_PROMPT
    assert "never estimate, compute or convert" in SYSTEM_PROMPT
