import json
from pathlib import Path

import pytest

from options_agent.grader import grade
from options_agent.questions import (
    IV,
    QUESTIONS,
    VOL_POINTS,
    FigureSpec,
    Question,
    answer_key,
    in_vol_points,
    skew,
    skew_point,
)

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"
SNAPSHOTS = Path(__file__).parents[1] / "snapshots"


def test_the_answer_key_reads_each_figure_straight_from_the_snapshot():
    question = Question(
        id="fixture",
        date="2025-11-20",
        text="ATM IV and 25-delta risk reversal of the 0DTE expiry?",
        purpose="test",
        status="answered",
        figures=(
            FigureSpec("atm_iv", "decimal_vol", IV, skew("2025-11-20", "atm_iv")),
            FigureSpec(
                "risk_reversal_25",
                "vol_points",
                VOL_POINTS,
                in_vol_points(skew_point("2025-11-20", 25, "risk_reversal")),
            ),
        ),
    )

    key = answer_key(question, FIXTURES)

    assert key.status == "answered"
    atm_iv, risk_reversal = key.figures
    assert (atm_iv.value, atm_iv.unit, atm_iv.tolerance) == (0.2415, "decimal_vol", IV)
    assert risk_reversal.value == pytest.approx(-0.8)
    assert risk_reversal.unit == "vol_points"


def test_an_unanswerable_question_has_no_figures_and_reads_no_snapshot():
    question = Question(
        id="fixture",
        date="2026-06-03",
        text="ATM IV on a day with no snapshot?",
        purpose="test",
        status="cannot_answer",
        figures=(FigureSpec("atm_iv", "decimal_vol", IV, skew("2026-06-03", "atm_iv")),),
    )

    key = answer_key(question, Path("no-such-folder"))

    assert key.status == "cannot_answer"
    assert key.figures == ()


def test_the_question_set_has_about_ten_questions_with_unique_ids_and_a_purpose_each():
    ids = [question.id for question in QUESTIONS]

    assert 8 <= len(QUESTIONS) <= 12
    assert len(set(ids)) == len(ids)
    assert all(question.purpose and question.figures for question in QUESTIONS)
    assert sum(question.status == "cannot_answer" for question in QUESTIONS) >= 2


real_snapshots = pytest.mark.skipif(
    not SNAPSHOTS.exists(), reason="the real snapshots are not in git"
)


@real_snapshots
@pytest.mark.parametrize("question", QUESTIONS, ids=lambda question: question.id)
def test_a_perfect_submission_scores_correct(question):
    key = answer_key(question, SNAPSHOTS)
    perfect = {
        "status": key.status,
        "answer": "perfect",
        "numbers": [
            {"name": f.name, "value": f.value, "unit": f.unit, "figure_id": f.name}
            for f in key.figures
        ],
        "missing_data": [],
    }

    assert grade(json.dumps(perfect), key) == "correct"


@real_snapshots
@pytest.mark.parametrize(
    "question",
    [q for q in QUESTIONS if q.status == "cannot_answer"],
    ids=lambda question: question.id,
)
def test_an_unanswerable_question_really_has_no_figure_in_the_snapshots(question):
    path = SNAPSHOTS / f"{question.date}.json"
    if not path.exists():
        return
    snapshot = json.loads(path.read_text(encoding="utf-8"))

    assert all(figure.read(snapshot) is None for figure in question.figures)
