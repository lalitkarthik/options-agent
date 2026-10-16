from pathlib import Path

import pytest
from mcp import Client

from options_agent.server import build_server

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"


async def test_list_dates_returns_each_day_with_provenance():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("list_dates")

    assert result.is_error is False
    assert result.structured_content == {
        "dates": [
            {
                "date": "2025-11-20",
                "snapshot": "2025-11-20.json",
                "as_of": "2025-11-20T15:45:00-05:00",
                "engine_commit": "345539eaef2caee1fd94d773d2eefe71de33ac9a",
            }
        ]
    }


async def test_get_skew_for_a_day_with_no_snapshot_is_a_tool_error_listing_the_valid_dates():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-21", "expiry": "2025-11-21"})

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_skew: "
        "No snapshot for date 2025-11-21. Available dates: 2025-11-20."
    )


async def test_get_skew_returns_each_figure_with_its_unit_and_id_and_the_provenance():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-20", "expiry": "2025-11-20"})

    skew = result.structured_content
    figures = {figure["id"]: figure for figure in skew["figures"]}
    assert result.is_error is False
    assert skew["snapshot"] == "2025-11-20.json"
    assert skew["as_of"] == "2025-11-20T15:45:00-05:00"
    assert skew["engine_commit"] == "345539eaef2caee1fd94d773d2eefe71de33ac9a"
    assert figures["skew:2025-11-20:2025-11-20:atm_iv"] == {
        "id": "skew:2025-11-20:2025-11-20:atm_iv",
        "value": 0.2415,
        "unit": "decimal_vol",
    }
    assert figures["skew:2025-11-20:2025-11-20:put_25_strike"]["unit"] == "index_points"
    risk_reversal = figures["skew:2025-11-20:2025-11-20:risk_reversal_25"]
    assert risk_reversal["unit"] == "vol_points"
    assert risk_reversal["value"] == pytest.approx(-0.8)


async def test_get_skew_lists_a_point_the_engine_could_not_compute_as_missing():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-20", "expiry": "2025-11-20"})

    skew = result.structured_content
    ids = [figure["id"] for figure in skew["figures"]]
    assert result.is_error is False
    assert "skew:2025-11-20:2025-11-20:put_10_iv" in ids
    assert "skew:2025-11-20:2025-11-20:call_10_iv" not in ids
    assert skew["missing"] == [
        "skew:2025-11-20:2025-11-20:call_10_iv",
        "skew:2025-11-20:2025-11-20:call_10_strike",
        "skew:2025-11-20:2025-11-20:call_10_skew",
        "skew:2025-11-20:2025-11-20:risk_reversal_10",
        "skew:2025-11-20:2025-11-20:butterfly_10",
    ]


async def test_get_skew_for_an_unknown_expiry_is_a_tool_error_listing_the_valid_expiries():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-20", "expiry": "2025-11-21"})

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_skew: "
        "No expiry 2025-11-21 on 2025-11-20. Available expiries: 2025-11-20."
    )


CONTRACTS = Path(__file__).parents[1] / "docs" / "design" / "tool-contracts.md"
REAL_SNAPSHOTS = Path(__file__).parents[1] / "snapshots"


def contract_descriptions() -> dict[str, str]:
    """Each tool's description as the contracts page quotes it, in page order, spaces collapsed."""
    descriptions = {}
    for section in CONTRACTS.read_text(encoding="utf-8").split("\n### ")[1:]:
        name = section.split("`")[1].split("(")[0]
        quote = [line.removeprefix(">") for line in section.splitlines() if line.startswith(">")]
        descriptions[name] = " ".join(" ".join(quote).split())
    return descriptions


async def test_the_seven_tools_are_listed_in_contract_order_with_the_contract_descriptions():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools

    contracts = contract_descriptions()
    assert [tool.name for tool in tools] == list(contracts)
    for tool in tools:
        assert " ".join(tool.description.split()) == contracts[tool.name]
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False


async def test_list_expiries_returns_the_days_expiries_with_provenance():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("list_expiries", {"date": "2025-11-20"})

    assert result.is_error is False
    assert result.structured_content == {
        "date": "2025-11-20",
        "snapshot": "2025-11-20.json",
        "as_of": "2025-11-20T15:45:00-05:00",
        "engine_commit": "345539eaef2caee1fd94d773d2eefe71de33ac9a",
        "expiries": ["2025-11-20"],
    }


async def test_list_expiries_for_a_day_with_no_snapshot_is_a_tool_error_listing_the_valid_dates():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("list_expiries", {"date": "2025-11-21"})

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool list_expiries: "
        "No snapshot for date 2025-11-21. Available dates: 2025-11-20."
    )


def strikes_in(figure_ids: list[str]) -> list[float]:
    """The strikes a chain result covers, read from its figure ids."""
    return sorted({float(figure_id.split(":")[3]) for figure_id in figure_ids})


async def test_get_chain_returns_five_strikes_each_side_of_the_forward_by_default():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_chain", {"date": "2025-11-20", "expiry": "2025-11-20"})

    chain = result.structured_content
    figures = {figure["id"]: figure for figure in chain["figures"]}
    assert result.is_error is False
    assert chain["expiry"] == "2025-11-20"
    assert chain["snapshot"] == "2025-11-20.json"
    assert chain["note"] is None
    assert chain["missing"] == []
    assert strikes_in(figures) == [6525, 6530, 6535, 6540, 6545, 6550, 6555, 6560, 6565, 6570]
    assert figures["chain:2025-11-20:2025-11-20:6550:mid_call"] == {
        "id": "chain:2025-11-20:2025-11-20:6550:mid_call",
        "value": 6.95,
        "unit": "index_points",
    }
    units = {figure_id.split(":")[4]: figure["unit"] for figure_id, figure in figures.items()}
    assert units == {
        "mid_call": "index_points",
        "mid_put": "index_points",
        "iv": "decimal_vol",
        "call_delta": "ratio",
        "put_delta": "ratio",
        "gamma": "per_index_point",
        "vega": "index_points_per_vol_point",
    }


async def test_get_chain_asked_for_more_than_fifteen_strikes_each_side_shows_fifteen_and_says_so():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_chain", {"date": "2025-11-20", "expiry": "2025-11-20", "strikes_each_side": 40}
        )

    chain = result.structured_content
    strikes = strikes_in([figure["id"] for figure in chain["figures"]] + chain["missing"])
    assert result.is_error is False
    assert len(strikes) == 30
    assert (strikes[0], strikes[-1]) == (6475, 6620)
    assert chain["note"] == (
        "Showing 15 strikes each side, the most this tool returns. Call get_chain with a smaller "
        "strikes_each_side, or use get_skew for figures at fixed deltas."
    )


async def test_get_chain_lists_the_figures_of_a_strike_with_no_usable_price_as_missing():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_chain", {"date": "2025-11-20", "expiry": "2025-11-20", "strikes_each_side": 15}
        )

    chain = result.structured_content
    ids = [figure["id"] for figure in chain["figures"]]
    assert result.is_error is False
    assert chain["note"] is None
    assert "chain:2025-11-20:2025-11-20:6620:mid_put" in ids
    assert chain["missing"] == [
        "chain:2025-11-20:2025-11-20:6620:mid_call",
        "chain:2025-11-20:2025-11-20:6620:iv",
        "chain:2025-11-20:2025-11-20:6620:call_delta",
        "chain:2025-11-20:2025-11-20:6620:put_delta",
        "chain:2025-11-20:2025-11-20:6620:gamma",
        "chain:2025-11-20:2025-11-20:6620:vega",
    ]


async def test_get_chain_for_an_unknown_expiry_is_a_tool_error_listing_the_valid_expiries():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_chain", {"date": "2025-11-20", "expiry": "2025-12-19"})

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_chain: "
        "No expiry 2025-12-19 on 2025-11-20. Available expiries: 2025-11-20."
    )


async def test_get_chain_rejects_fewer_than_one_strike_each_side_before_running():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_chain", {"date": "2025-11-20", "expiry": "2025-11-20", "strikes_each_side": 0}
        )

    assert result.is_error is True
    assert "greater than or equal to 1" in result.content[0].text


async def test_get_realised_vol_returns_the_kind_asked_for_as_a_decimal_vol():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_realised_vol", {"date": "2025-11-20", "kind": "close_to_close_20"}
        )

    realised = result.structured_content
    assert result.is_error is False
    assert realised["kind"] == "close_to_close_20"
    assert realised["engine_commit"] == "345539eaef2caee1fd94d773d2eefe71de33ac9a"
    assert realised["figures"] == [
        {
            "id": "realised:2025-11-20:close_to_close_20:realised_vol",
            "value": 0.1332,
            "unit": "decimal_vol",
        }
    ]
    assert realised["missing"] == []


async def test_get_realised_vol_rejects_an_unknown_kind_before_running():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_realised_vol", {"date": "2025-11-20", "kind": "weekly"}
        )

    assert result.is_error is True
    assert "Input should be 'since_open' or 'close_to_close_20'" in result.content[0].text


async def test_get_implied_move_returns_the_move_the_atm_iv_and_the_gap_in_vol_points():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_implied_move", {"date": "2025-11-20", "expiry": "2025-11-20"}
        )

    move = result.structured_content
    figures = {figure["id"]: figure for figure in move["figures"]}
    assert result.is_error is False
    assert move["expiry"] == "2025-11-20"
    assert move["as_of"] == "2025-11-20T15:45:00-05:00"
    assert move["missing"] == []
    assert figures["move:2025-11-20:2025-11-20:implied_move"] == {
        "id": "move:2025-11-20:2025-11-20:implied_move",
        "value": 15.6,
        "unit": "index_points",
    }
    assert figures["move:2025-11-20:2025-11-20:atm_iv"]["value"] == 0.2415
    gap = figures["move:2025-11-20:2025-11-20:implied_realised_gap"]
    assert gap["unit"] == "vol_points"
    assert gap["value"] == pytest.approx(2.85)


async def test_get_implied_move_for_an_unknown_expiry_is_a_tool_error_listing_the_valid_expiries():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_implied_move", {"date": "2025-11-20", "expiry": "2025-11-21"}
        )

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_implied_move: "
        "No expiry 2025-11-21 on 2025-11-20. Available expiries: 2025-11-20."
    )


async def test_get_gamma_exposure_for_all_expiries_returns_the_flip_and_four_walls_each_side():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_gamma_exposure", {"date": "2025-11-20", "scope": "all"}
        )

    gamma = result.structured_content
    values = {figure["id"]: figure["value"] for figure in gamma["figures"]}
    assert result.is_error is False
    assert gamma["scope"] == "all"
    assert gamma["missing"] == []
    assert gamma["figures"][0] == {
        "id": "gamma:2025-11-20:all:net_total",
        "value": -48165236128.48,
        "unit": "usd_per_1pct_move",
    }
    assert values["gamma:2025-11-20:all:flip"] == 6715.02
    assert values["gamma:2025-11-20:all:resistance_1"] == 7000.0
    assert values["gamma:2025-11-20:all:support_4"] == 6530.0
    assert {figure["unit"] for figure in gamma["figures"][1:]} == {"index_points"}


async def test_get_gamma_exposure_with_no_flip_in_range_lists_the_flip_as_missing():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_gamma_exposure", {"date": "2025-11-20", "scope": "0dte"}
        )

    gamma = result.structured_content
    ids = [figure["id"] for figure in gamma["figures"]]
    assert result.is_error is False
    assert gamma["missing"] == ["gamma:2025-11-20:0dte:flip"]
    assert ids == [
        "gamma:2025-11-20:0dte:net_total",
        "gamma:2025-11-20:0dte:spot",
        "gamma:2025-11-20:0dte:support_1",
        "gamma:2025-11-20:0dte:support_2",
        "gamma:2025-11-20:0dte:support_3",
        "gamma:2025-11-20:0dte:support_4",
    ]


async def test_get_gamma_exposure_for_a_day_with_no_snapshot_is_a_tool_error():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_gamma_exposure", {"date": "2026-01-02", "scope": "all"}
        )

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_gamma_exposure: "
        "No snapshot for date 2026-01-02. Available dates: 2025-11-20."
    )


@pytest.mark.skipif(not REAL_SNAPSHOTS.is_dir(), reason="the real snapshots are not in git")
async def test_every_tool_answers_on_every_real_snapshot_day():
    async with Client(build_server(REAL_SNAPSHOTS), raise_exceptions=True) as client:
        dates = (await client.call_tool("list_dates")).structured_content["dates"]
        for day in dates:
            date = day["date"]
            listed = await client.call_tool("list_expiries", {"date": date})
            zero_dte = listed.structured_content["expiries"][0]
            assert zero_dte == date
            calls = [
                ("get_chain", {"date": date, "expiry": zero_dte}),
                ("get_skew", {"date": date, "expiry": zero_dte}),
                ("get_realised_vol", {"date": date, "kind": "since_open"}),
                ("get_realised_vol", {"date": date, "kind": "close_to_close_20"}),
                ("get_implied_move", {"date": date, "expiry": zero_dte}),
                ("get_gamma_exposure", {"date": date, "scope": "0dte"}),
                ("get_gamma_exposure", {"date": date, "scope": "all"}),
            ]
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                assert result.is_error is False, (name, arguments, result.content)
                assert result.structured_content["figures"], (name, arguments)
