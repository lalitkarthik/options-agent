import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from options_agent.grader import AnswerKey, KeyFigure, Status

VERSION = "1-A"

# Tolerances, each in its figure's unit: about the rounding an answer may fairly use.
IV = 0.0005  # decimal_vol: 0.05 vol points
VOL_POINTS = 0.05
MOVE = 0.05  # index_points
LEVEL = 0.5  # index_points: a fitted level such as the gamma flip
STRIKE = 0.0  # index_points: a strike is exact
EXPOSURE = 1e8  # usd_per_1pct_move: $100m

Read = Callable[[dict], float | None]


@dataclass(frozen=True)
class FigureSpec:
    name: str
    unit: str
    tolerance: float
    read: Read


@dataclass(frozen=True)
class Question:
    id: str
    date: str
    text: str
    purpose: str
    status: Status
    figures: tuple[FigureSpec, ...]


def skew(expiry: str, field: str) -> Read:
    return lambda snapshot: next(s for s in snapshot["skews"] if s["expiry"] == expiry)[field]


def skew_point(expiry: str, delta: int, field: str) -> Read:
    def read(snapshot: dict) -> float | None:
        record = next(s for s in snapshot["skews"] if s["expiry"] == expiry)
        return next(p for p in record["points"] if p["delta"] == delta)[field]

    return read


def gamma(expiry: str | None, field: str) -> Read:
    """`expiry` None is the engine's all-expiries record."""
    return lambda snapshot: next(g for g in snapshot["gamma"] if g["expiry"] == expiry)[field]


def first_wall(expiry: str | None, side: str) -> Read:
    return lambda snapshot: gamma(expiry, side)(snapshot)[0]


def realised(field: str) -> Read:
    return lambda snapshot: snapshot["realised"][field]


def gap(expiry: str) -> Read:
    return lambda snapshot: snapshot["gaps"][expiry]


def in_vol_points(read: Read) -> Read:
    """The engine keeps volatility differences as decimals; the tools report vol points."""

    def converted(snapshot: dict) -> float | None:
        value = read(snapshot)
        return None if value is None else value * 100

    return converted


QUESTIONS = (
    Question(
        id="atm-iv-0dte-calm",
        date="2026-06-02",
        text="What was the at-the-money implied volatility of the 0DTE SPXW expiry at 15:45 New "
        "York time on 2026-06-02?",
        purpose="One figure from one tool, on the calmest day of the year.",
        status="answered",
        figures=(FigureSpec("atm_iv", "decimal_vol", IV, skew("2026-06-02", "atm_iv")),),
    ),
    Question(
        id="term-structure-fomc",
        date="2026-03-18",
        text="On 2026-03-18 (an FOMC day) at 15:45 New York time, what were the at-the-money "
        "implied volatilities of the 2026-03-19 and 2026-04-17 SPXW expiries?",
        purpose="Two expiries in one answer: two get_skew calls, kept apart.",
        status="answered",
        figures=(
            FigureSpec("atm_iv_2026-03-19", "decimal_vol", IV, skew("2026-03-19", "atm_iv")),
            FigureSpec("atm_iv_2026-04-17", "decimal_vol", IV, skew("2026-04-17", "atm_iv")),
        ),
    ),
    Question(
        id="risk-reversal-quarterly",
        date="2026-03-20",
        text="What was the 25-delta risk reversal of the 2026-04-17 SPXW expiry at 15:45 New York "
        "time on 2026-03-20, in vol points?",
        purpose="A skew figure in vol points, not decimals: tests the unit.",
        status="answered",
        figures=(
            FigureSpec(
                "risk_reversal_25",
                "vol_points",
                VOL_POINTS,
                in_vol_points(skew_point("2026-04-17", 25, "risk_reversal")),
            ),
        ),
    ),
    Question(
        id="implied-realised-gap-volatile",
        date="2025-11-20",
        text="On 2025-11-20 at 15:45 New York time, how far was the 0DTE at-the-money implied "
        "volatility above or below the realised volatility since the open, in vol points?",
        purpose="A comparison the tool computes; the agent must not do the subtraction itself.",
        status="answered",
        figures=(
            FigureSpec(
                "implied_realised_gap", "vol_points", VOL_POINTS, in_vol_points(gap("2025-11-20"))
            ),
        ),
    ),
    Question(
        id="realised-close-to-close",
        date="2026-05-04",
        text="What was the 20-session close-to-close realised volatility of the S&P 500 on "
        "2026-05-04?",
        purpose="Picking the right realised-volatility kind.",
        status="answered",
        figures=(FigureSpec("realised_vol", "decimal_vol", IV, realised("close_to_close_20")),),
    ),
    Question(
        id="implied-move-fomc",
        date="2026-03-18",
        text="How many index points was the 0DTE SPXW straddle pricing in at 15:45 New York time "
        "on 2026-03-18?",
        purpose="The implied move, in index points.",
        status="answered",
        figures=(
            FigureSpec("implied_move", "index_points", MOVE, skew("2026-03-18", "implied_move")),
        ),
    ),
    Question(
        id="gamma-flip-and-call-wall",
        date="2026-05-04",
        text="Across all SPXW expiries at 15:45 New York time on 2026-05-04, where was the gamma "
        "flip, and which strike was the call wall?",
        purpose="Two gamma figures with different tolerances: a fitted level and an exact strike.",
        status="answered",
        figures=(
            FigureSpec("flip", "index_points", LEVEL, gamma(None, "flip")),
            FigureSpec("resistance_1", "index_points", STRIKE, first_wall(None, "resistance")),
        ),
    ),
    Question(
        id="net-gamma-0dte-calm",
        date="2026-06-02",
        text="What was the net gamma exposure of the 0DTE SPXW options at 15:45 New York time on "
        "2026-06-02, in dollars per 1% index move?",
        purpose="A large number with its own unit.",
        status="answered",
        figures=(
            FigureSpec(
                "net_total", "usd_per_1pct_move", EXPOSURE, gamma("2026-06-02", "net_total")
            ),
        ),
    ),
    Question(
        id="no-snapshot-day",
        date="2026-06-03",
        text="What was the at-the-money implied volatility of the 0DTE SPXW expiry at 15:45 New "
        "York time on 2026-06-03?",
        purpose="Unanswerable: no snapshot for that day. The right answer is cannot_answer.",
        status="cannot_answer",
        figures=(FigureSpec("atm_iv", "decimal_vol", IV, skew("2026-06-03", "atm_iv")),),
    ),
    Question(
        id="no-gamma-flip-0dte",
        date="2025-11-20",
        text="Where was the 0DTE SPXW gamma flip at 15:45 New York time on 2025-11-20?",
        purpose="Unanswerable: the engine found no zero crossing near the index that day.",
        status="cannot_answer",
        figures=(FigureSpec("flip", "index_points", LEVEL, gamma("2025-11-20", "flip")),),
    ),
)


def answer_key(question: Question, snapshot_dir: Path) -> AnswerKey:
    """Read a question's correct figures straight from its snapshot, not through the tools."""
    if question.status == "cannot_answer":
        return AnswerKey(status="cannot_answer")
    path = snapshot_dir / f"{question.date}.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    figures = tuple(
        KeyFigure(name=f.name, value=f.read(snapshot), unit=f.unit, tolerance=f.tolerance)
        for f in question.figures
    )
    return AnswerKey(status="answered", figures=figures)
