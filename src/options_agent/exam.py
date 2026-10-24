import ssl
from dataclasses import asdict
from pathlib import Path

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from inspect_ai import Epochs, Task, eval, task
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ModelCost, get_model, set_model_cost
from inspect_ai.scorer import Metric, SampleScore, Score, Target, metric, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import store
from mcp import Client

from options_agent.agent import (
    DEFAULT_BUDGET,
    MODEL,
    PRICE_CACHE_READ,
    PRICE_CACHE_WRITE,
    PRICE_INPUT,
    PRICE_OUTPUT,
    run_agent,
)
from options_agent.grader import MARKS, AnswerKey, KeyFigure, Outcome, grade
from options_agent.questions import QUESTIONS, VERSION, Question, answer_key
from options_agent.server import build_server

OUTCOMES: tuple[Outcome, ...] = ("correct", "incorrect", "not_attempted")

# `inspect eval` runs a task from the task file's folder, so the default is not relative.
SNAPSHOTS = Path(__file__).resolve().parents[2] / "snapshots"

TRIALS = 5
# A backstop above the loop's own 12-turn cap: each tool result is a message of its own.
MESSAGE_LIMIT = 60


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
            metadata={"stop": state.store.get("stop")},
        )

    return score


@agent
def options_agent(snapshot_dir: Path) -> Agent:
    """The hand-written loop as an Inspect agent: its Claude calls go through the bridge."""

    async def execute(state: AgentState) -> AgentState:
        async with (
            agent_bridge(state, forward_generation_config=True) as bridge,
            Client(build_server(snapshot_dir)) as mcp,
        ):
            outcome = await run_agent(
                state.messages[-1].text, claude=AsyncAnthropic(), mcp=mcp, model="inspect"
            )
        store().set("stop", outcome.stop)
        if outcome.submission is not None:
            bridge.state.output.completion = outcome.submission.model_dump_json()
        return bridge.state

    return execute


def exam_task(questions: tuple[Question, ...], snapshot_dir: Path) -> Task:
    """The questions as an exam: the agent answers each one five times, within limits."""
    return Task(
        dataset=dataset(questions, snapshot_dir),
        solver=options_agent(snapshot_dir),
        scorer=exam_grader(),
        epochs=Epochs(TRIALS, ["mean", f"pass_k_{TRIALS}"]),
        message_limit=MESSAGE_LIMIT,
        version=VERSION,
    )


@task
def exam(snapshot_dir: str = str(SNAPSHOTS)) -> Task:
    return exam_task(QUESTIONS, Path(snapshot_dir))


def results(log: EvalLog) -> dict[str, float]:
    """The exam's table from one log: per-trial averages, pass^5, cost and time per trial."""
    metrics = {
        score.reducer: {name: m.value for name, m in score.metrics.items()}
        for score in log.results.scores
    }
    mean, every_trial = metrics["mean"], metrics[f"pass_k_{TRIALS}"]
    trials = len(log.samples)
    questions = len({sample.id for sample in log.samples})
    cost = sum(u.total_cost or 0 for s in log.samples for u in s.model_usage.values())
    return {
        "net score": mean["net_score"],
        "correct": mean["correct"],
        "incorrect": mean["incorrect"],
        "not attempted": mean["not_attempted"],
        f"pass^{TRIALS}": every_trial["correct"] / questions,
        "cost per question ($)": cost / trials,
        "time per question (s)": sum(s.total_time or 0 for s in log.samples) / trials,
    }


def main() -> None:
    """Run the exam on Claude Sonnet 5.5 and print its table: uv run exam."""
    set_model_cost(
        f"anthropic/{MODEL}",
        ModelCost(
            input=PRICE_INPUT,
            output=PRICE_OUTPUT,
            input_cache_write=PRICE_CACHE_WRITE,
            input_cache_read=PRICE_CACHE_READ,
        ),
    )
    # The same Windows certificate fix as agent.main(), for Inspect's own Anthropic client.
    http_client = DefaultAsyncHttpxClient(verify=ssl.create_default_context())
    model = get_model(f"anthropic/{MODEL}", http_client=http_client)
    # cost_limit needs the prices above, so it is set here rather than on the task.
    [log] = eval(exam(), model=model, cost_limit=DEFAULT_BUDGET.dollars)
    if log.status == "success":
        for name, value in results(log).items():
            print(f"{name:>22}  {value:.4g}")
