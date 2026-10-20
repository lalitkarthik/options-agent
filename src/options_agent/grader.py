from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

Status = Literal["answered", "cannot_answer"]
Outcome = Literal["correct", "incorrect", "not_attempted"]

MARKS: dict[Outcome, int] = {"correct": 1, "not_attempted": 0, "incorrect": -3}


class Number(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    value: float
    unit: str
    figure_id: str


class Submission(BaseModel):
    model_config = ConfigDict(strict=True)

    status: Status
    answer: str
    numbers: list[Number]
    missing_data: list[str]


@dataclass(frozen=True)
class KeyFigure:
    name: str
    value: float
    unit: str
    tolerance: float


@dataclass(frozen=True)
class AnswerKey:
    status: Status
    figures: tuple[KeyFigure, ...] = ()


def matches(number: Number, figure: KeyFigure) -> bool:
    """Same unit, ignoring case, and a value within the figure's tolerance."""
    same_unit = number.unit.lower() == figure.unit.lower()
    return same_unit and abs(number.value - figure.value) <= figure.tolerance


def grade(submission_json: str | None, key: AnswerKey) -> Outcome:
    """Mark one submission against its answer key."""
    if submission_json is None:
        return "not_attempted"
    try:
        submission = Submission.model_validate_json(submission_json)
    except ValidationError:
        return "not_attempted"

    if submission.status == "cannot_answer":
        return "correct" if key.status == "cannot_answer" else "not_attempted"
    if key.status == "cannot_answer":
        return "incorrect"
    for figure in key.figures:
        if not any(matches(number, figure) for number in submission.numbers):
            return "incorrect"
    return "correct"


def net_score(outcomes: list[Outcome]) -> int:
    """+1 per correct answer, 0 per cannot-answer or not attempted, -3 per wrong answer."""
    return sum(MARKS[outcome] for outcome in outcomes)
