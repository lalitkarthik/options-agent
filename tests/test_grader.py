import json

import pytest

from options_agent.grader import AnswerKey, KeyFigure, grade, net_score

ATM_IV = AnswerKey(
    status="answered",
    figures=(KeyFigure(name="atm_iv", value=0.2415, unit="decimal_vol", tolerance=0.0005),),
)
NO_SNAPSHOT = AnswerKey(status="cannot_answer")


def submission(status="answered", value=0.2415, unit="decimal_vol"):
    numbers = []
    if status == "answered":
        numbers = [
            {
                "name": "atm_iv",
                "value": value,
                "unit": unit,
                "figure_id": "skew:2025-11-20:2025-11-20:atm_iv",
            }
        ]
    return json.dumps(
        {
            "status": status,
            "answer": "The 0DTE ATM IV was 24.15%.",
            "numbers": numbers,
            "missing_data": [] if status == "answered" else ["no snapshot for that day"],
        }
    )


@pytest.mark.parametrize(
    ("submitted", "key", "outcome"),
    [
        pytest.param(submission(), ATM_IV, "correct", id="right"),
        pytest.param(submission(value=0.2419), ATM_IV, "correct", id="within tolerance"),
        pytest.param(submission(unit="DECIMAL_VOL"), ATM_IV, "correct", id="unit case ignored"),
        pytest.param(submission(value=0.2425), ATM_IV, "incorrect", id="wrong value"),
        pytest.param(submission(unit="vol_points"), ATM_IV, "incorrect", id="wrong unit"),
        pytest.param(submission("cannot_answer"), ATM_IV, "not_attempted", id="abstained"),
        pytest.param(submission("cannot_answer"), NO_SNAPSHOT, "correct", id="rightly abstained"),
        pytest.param(submission(), NO_SNAPSHOT, "incorrect", id="answered the unanswerable"),
        pytest.param('{"status": "answered"}', ATM_IV, "not_attempted", id="malformed"),
        pytest.param("The ATM IV is 24%", ATM_IV, "not_attempted", id="not json"),
        pytest.param(None, ATM_IV, "not_attempted", id="no submission"),
    ],
)
def test_grade(submitted, key, outcome):
    assert grade(submitted, key) == outcome


def test_a_correct_answer_needs_every_figure_in_the_key():
    key = AnswerKey(
        status="answered",
        figures=(
            KeyFigure(name="atm_iv", value=0.2415, unit="decimal_vol", tolerance=0.0005),
            KeyFigure(name="forward", value=6548.3, unit="index_points", tolerance=0.5),
        ),
    )

    assert grade(submission(), key) == "incorrect"


def test_net_score_is_plus_one_zero_minus_three():
    assert net_score(["correct", "correct", "not_attempted", "incorrect"]) == -1
