from dataclasses import asdict
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import Metric, SampleScore, Score, Target, metric, scorer
from inspect_ai.solver import TaskState

from options_agent.grader import MARKS, AnswerKey, KeyFigure, Outcome, grade
from options_agent.questions import QUESTIONS, VERSION, Question, answer_key

OUTCOMES: tuple[Outcome, ...] = ("correct", "incorrect", "not_attempted")

# `inspect eval` runs a task from the task file's folder, so the default is not relative.
SNAPSHOTS = Path(__file__).resolve().parents[2] / "snapshots"


def dataset(questions: tuple[Question, ...], snapshot_dir: Path) -> MemoryDataset:
    """One Inspect sample per question, its answer key carried in the sample's metadata."""
    samples = [
        Sample(
            id=question.id,
            input=question.text,
            metadata={
                "date": question.date,
                "purpose": question.purpose,
                "key": asdict(answer_key(question, snapshot_dir)),
            },
        )
        for question in questions
    ]
    return MemoryDataset(samples, name="options-exam")


def key_from_metadata(metadata: dict) -> AnswerKey:
    key = metadata["key"]
    figures = tuple(KeyFigure(**figure) for figure in key["figures"])
    return AnswerKey(status=key["status"], figures=figures)


def total(outcome: Outcome) -> Metric:
    def metric_fn(scores: list[SampleScore]) -> float:
        return sum(s.score.value[outcome] for s in scores)

    return metric_fn


@metric
def correct() -> Metric:
    return total("correct")


@metric
def incorrect() -> Metric:
    return total("incorrect")


@metric
def not_attempted() -> Metric:
    return total("not_attempted")


@metric
def net_score() -> Metric:
    def metric_fn(scores: list[SampleScore]) -> float:
        return sum(MARKS[o] * s.score.value[o] for s in scores for o in OUTCOMES)

    return metric_fn


@scorer(metrics=[net_score(), correct(), incorrect(), not_attempted()])
def exam_grader():
    async def score(state: TaskState, target: Target) -> Score:
        submission = state.output.completion or None
        outcome = grade(submission, key_from_metadata(state.metadata))
        return Score(
            value={o: int(o == outcome) for o in OUTCOMES},
            answer=submission,
            explanation=outcome,
        )

    return score


@task
def exam(snapshot_dir: str = str(SNAPSHOTS)) -> Task:
    return Task(
        dataset=dataset(QUESTIONS, Path(snapshot_dir)),
        scorer=exam_grader(),
        version=VERSION,
    )
