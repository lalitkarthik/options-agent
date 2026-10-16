import json
import sys
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

Unit = Literal[
    "decimal_vol",
    "vol_points",
    "index_points",
    "ratio",
    "per_index_point",
    "index_points_per_vol_point",
    "usd_per_1pct_move",
]

MAX_STRIKES_EACH_SIDE = 15
TRUNCATED_NOTE = (
    "Showing 15 strikes each side, the most this tool returns. Call get_chain with a smaller "
    "strikes_each_side, or use get_skew for figures at fixed deltas."
)

# Each chain column the tool returns, with its unit.
CHAIN_COLUMNS: dict[str, Unit] = {
    "mid_call": "index_points",
    "mid_put": "index_points",
    "iv": "decimal_vol",
    "call_delta": "ratio",
    "put_delta": "ratio",
    "gamma": "per_index_point",
    "vega": "index_points_per_vol_point",
}


class Provenance(BaseModel):
    date: str
    snapshot: str
    as_of: str
    engine_commit: str


class DateList(BaseModel):
    dates: list[Provenance]


class Figure(BaseModel):
    id: str
    value: float
    unit: Unit


class ExpiryList(Provenance):
    expiries: list[str]


class Chain(Provenance):
    expiry: str
    figures: list[Figure]
    missing: list[str]
    note: str | None


class Skew(Provenance):
    expiry: str
    figures: list[Figure]
    missing: list[str]


class RealisedVol(Provenance):
    kind: str
    figures: list[Figure]
    missing: list[str]


class ImpliedMove(Provenance):
    expiry: str
    figures: list[Figure]
    missing: list[str]


class GammaExposure(Provenance):
    scope: str
    figures: list[Figure]
    missing: list[str]


class Figures:
    """Collects one result's figures, putting a value the engine could not compute in `missing`."""

    def __init__(self, id_prefix: str):
        self.id_prefix = id_prefix
        self.figures: list[Figure] = []
        self.missing: list[str] = []

    def add(self, name: str, value: float | None, unit: Unit) -> None:
        figure_id = f"{self.id_prefix}:{name}"
        if value is None:
            self.missing.append(figure_id)
        else:
            self.figures.append(Figure(id=figure_id, value=value, unit=unit))


def load_snapshots(snapshot_dir: Path) -> dict[str, dict]:
    """Read every snapshot file in the folder, keyed by its day, in date order."""
    snapshots = {}
    for path in sorted(snapshot_dir.glob("*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["file"] = path.name
        snapshots[snapshot["day"]] = snapshot
    return snapshots


def provenance(snapshot: dict) -> dict:
    """The fields every result carries to say which snapshot its figures came from."""
    return {
        "date": snapshot["day"],
        "snapshot": snapshot["file"],
        "as_of": snapshot["as_of"],
        "engine_commit": snapshot["engine_commit"],
    }


def expiries(snapshot: dict) -> list[str]:
    """Every expiry the engine priced on the snapshot day, in date order."""
    return sorted(event["expiry"] for event in snapshot["chain_events"])


def check_expiry(snapshot: dict, expiry: str) -> None:
    valid = expiries(snapshot)
    if expiry not in valid:
        available = ", ".join(valid)
        raise ToolError(
            f"No expiry {expiry} on {snapshot['day']}. Available expiries: {available}."
        )


def to_vol_points(value: float | None) -> float | None:
    """Turn a decimal volatility difference (0.008) into vol points (0.8)."""
    return None if value is None else value * 100


def build_server(snapshot_dir: Path) -> MCPServer:
    server = MCPServer("options-agent")
    # Snapshots are frozen, so they are read once rather than on every tool call.
    snapshots = load_snapshots(snapshot_dir)

    def find_snapshot(date: str) -> dict:
        if date not in snapshots:
            available = ", ".join(snapshots)
            raise ToolError(f"No snapshot for date {date}. Available dates: {available}.")
        return snapshots[date]

    @server.tool(annotations=READ_ONLY)
    def list_dates() -> DateList:
        """List the snapshot days the other tools can answer about.

        Each day comes with its provenance: the snapshot file, the as-of time (15:45 New York,
        with its UTC offset) and the engine commit that built it. Call this first to find a
        valid `date` for the other tools.
        """
        return DateList(dates=[Provenance(**provenance(s)) for s in snapshots.values()])

    @server.tool(annotations=READ_ONLY)
    def list_expiries(date: str) -> ExpiryList:
        """List the expiries of the SPXW chain on one snapshot day.

        `date` is a snapshot day from list_dates, as YYYY-MM-DD. Returns every expiry the
        engine priced that day, in date order, as YYYY-MM-DD; the first is the 0DTE expiry,
        which expires that same day. Use one of these as `expiry` in get_chain, get_skew and
        get_implied_move.
        """
        snapshot = find_snapshot(date)
        return ExpiryList(**provenance(snapshot), expiries=expiries(snapshot))

    @server.tool(annotations=READ_ONLY)
    def get_chain(
        date: str, expiry: str, strikes_each_side: Annotated[int, Field(ge=1)] = 5
    ) -> Chain:
        """Get the option chain of one expiry around its forward, as of 15:45 New York.

        `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries from
        list_expiries, both as YYYY-MM-DD. `strikes_each_side` is how many strikes to show
        below and above the forward: 5 by default, at most 15. Each strike has the call and put
        mid prices in index points, the implied volatility of its out-of-the-money side as a
        yearly decimal, the call and put delta, gamma per index point, and vega in index points
        per vol point. A strike with no usable price has its figures listed in `missing`. For
        skew at fixed deltas use get_skew; this tool does not return open interest or gamma
        exposure.
        """
        snapshot = find_snapshot(date)
        check_expiry(snapshot, expiry)

        note = None
        if strikes_each_side > MAX_STRIKES_EACH_SIDE:
            strikes_each_side = MAX_STRIKES_EACH_SIDE
            note = TRUNCATED_NOTE

        forward = next(e["forward"] for e in snapshot["chain_events"] if e["expiry"] == expiry)
        columns = snapshot["strikes"][expiry]["columns"]
        # Row numbers of the strikes below the forward and at or above it, nearest first.
        rows = sorted(range(len(columns["strike"])), key=lambda row: columns["strike"][row])
        below = [row for row in rows if columns["strike"][row] < forward][-strikes_each_side:]
        above = [row for row in rows if columns["strike"][row] >= forward][:strikes_each_side]

        figures = Figures(f"chain:{date}:{expiry}")
        for row in below + above:
            strike = f"{columns['strike'][row]:g}"
            for column, unit in CHAIN_COLUMNS.items():
                figures.add(f"{strike}:{column}", columns[column][row], unit)

        return Chain(
            **provenance(snapshot),
            expiry=expiry,
            figures=figures.figures,
            missing=figures.missing,
            note=note,
        )

    @server.tool(annotations=READ_ONLY)
    def get_skew(date: str, expiry: str) -> Skew:
        """Get one expiry's skew figures on one snapshot day, as of 15:45 New York.

        `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries, both
        as YYYY-MM-DD. Returns the forward, the ATM implied volatility, and at the 25, 10, 5
        and 1 delta points the put and call IV, their strikes, each side's skew against ATM,
        the risk reversal (call IV minus put IV) and the butterfly. Delta is forward delta.
        IVs are yearly decimals (0.2415 is 24.15%); skews, risk reversals and butterflies are
        in vol points; the forward and strikes are in index points. A figure the engine could
        not compute is listed in `missing` by its id instead of being returned.
        """
        snapshot = find_snapshot(date)
        check_expiry(snapshot, expiry)
        skew = next(skew for skew in snapshot["skews"] if skew["expiry"] == expiry)

        figures = Figures(f"skew:{date}:{expiry}")
        figures.add("forward", skew["forward"], "index_points")
        figures.add("atm_iv", skew["atm_iv"], "decimal_vol")
        for point in skew["points"]:
            delta = point["delta"]
            for side in ("put", "call"):
                figures.add(f"{side}_{delta}_iv", point[f"{side}_iv"], "decimal_vol")
                figures.add(f"{side}_{delta}_strike", point[f"{side}_strike"], "index_points")
                skew_points = to_vol_points(point[f"{side}_skew"])
                figures.add(f"{side}_{delta}_skew", skew_points, "vol_points")
            risk_reversal = to_vol_points(point["risk_reversal"])
            figures.add(f"risk_reversal_{delta}", risk_reversal, "vol_points")
            figures.add(f"butterfly_{delta}", to_vol_points(point["butterfly"]), "vol_points")

        return Skew(
            **provenance(snapshot),
            expiry=expiry,
            figures=figures.figures,
            missing=figures.missing,
        )

    @server.tool(annotations=READ_ONLY)
    def get_realised_vol(
        date: str, kind: Literal["since_open", "close_to_close_20"]
    ) -> RealisedVol:
        """Get the realised volatility of the S&P 500 index on one snapshot day, up to 15:45
        New York.

        `date` is a snapshot day from list_dates, as YYYY-MM-DD. `kind` is `since_open`: from
        five-minute index moves since the 09:30 open, adjusted by the engine's time-of-day
        profile of the past 30 sessions; or `close_to_close_20`: from the daily closes of the
        past 20 sessions. Both are yearly decimals (0.10 is 10%), the same scale as implied
        volatility. For implied minus realised volatility use get_implied_move.
        """
        snapshot = find_snapshot(date)

        figures = Figures(f"realised:{date}:{kind}")
        figures.add("realised_vol", snapshot["realised"][kind], "decimal_vol")

        return RealisedVol(
            **provenance(snapshot),
            kind=kind,
            figures=figures.figures,
            missing=figures.missing,
        )

    @server.tool(annotations=READ_ONLY)
    def get_implied_move(date: str, expiry: str) -> ImpliedMove:
        """Get the index move one expiry's options price in, and how implied volatility
        compares with realised, as of 15:45 New York.

        `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries, both
        as YYYY-MM-DD. Returns the implied move in index points (the move the at-the-money
        straddle prices in, up or down, by expiry), the ATM implied volatility as a yearly
        decimal, and the implied-realised gap in vol points: ATM implied volatility minus
        realised volatility since the open. A positive gap means options price in more
        movement than the index has shown today.
        """
        snapshot = find_snapshot(date)
        check_expiry(snapshot, expiry)
        skew = next(skew for skew in snapshot["skews"] if skew["expiry"] == expiry)

        figures = Figures(f"move:{date}:{expiry}")
        figures.add("implied_move", skew["implied_move"], "index_points")
        figures.add("atm_iv", skew["atm_iv"], "decimal_vol")
        gap = to_vol_points(snapshot["gaps"].get(expiry))
        figures.add("implied_realised_gap", gap, "vol_points")

        return ImpliedMove(
            **provenance(snapshot),
            expiry=expiry,
            figures=figures.figures,
            missing=figures.missing,
        )

    @server.tool(annotations=READ_ONLY)
    def get_gamma_exposure(date: str, scope: Literal["0dte", "all"]) -> GammaExposure:
        """Get the gamma exposure of SPXW options on one snapshot day, as of 15:45 New York.

        `date` is a snapshot day from list_dates, as YYYY-MM-DD. `scope` is `0dte` for the
        options expiring that day only, or `all` for every expiry together. Gamma exposure is
        how many dollars of the index market makers would buy or sell for a 1% index move, from
        each option's gamma and open interest, calls above zero and puts below. Returns the net
        total, the index level at the time, the gamma flip (the index level nearest today's
        where the total crosses zero), and the walls: resistance, the strikes with the largest
        positive exposure, and support, the strikes with the most negative, strongest first. If
        the engine found no crossing near the index, the flip is listed in `missing`: there is
        no gamma flip in range, which is an answer in itself. Exposure per strike is not
        returned.
        """
        snapshot = find_snapshot(date)
        # The engine publishes one gamma entry per expiry, and one with no expiry for them all.
        wanted = date if scope == "0dte" else None
        gamma = next(gamma for gamma in snapshot["gamma"] if gamma["expiry"] == wanted)

        figures = Figures(f"gamma:{date}:{scope}")
        figures.add("net_total", gamma["net_total"], "usd_per_1pct_move")
        figures.add("spot", gamma["spot"], "index_points")
        figures.add("flip", gamma["flip"], "index_points")
        for side in ("resistance", "support"):
            for rank, strike in enumerate(gamma[side], start=1):
                figures.add(f"{side}_{rank}", strike, "index_points")

        return GammaExposure(
            **provenance(snapshot),
            scope=scope,
            figures=figures.figures,
            missing=figures.missing,
        )

    return server


def main() -> None:
    """Serve the seven tools over stdio, from the snapshots folder given (default: ./snapshots)."""
    snapshot_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "snapshots")
    build_server(snapshot_dir).run()
