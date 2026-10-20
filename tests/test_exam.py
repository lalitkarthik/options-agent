import json
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.model import ModelOutput, get_model

from options_agent.exam import dataset, exam_grader
from options_agent.questions import IV, FigureSpec, Question, skew

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"

ATM_IV = Question(
    id="atm-iv",
    date="2025-11-20",
    text="What was the 0DTE ATM IV on 2025-11-20?",
    purpose="test",
    status="answered",
    figures=(FigureSpec("atm_iv", "decimal_vol", IV, skew("2025-11-20", "atm_iv")),),
)
NO_SNAPSHOT = Question(
    id="no-snapshot",
    date="2026-06-03",
    text="What was the 0DTE ATM IV on 2026-06-03?",
    purpose="test",
    status="cannot_answer",
    figures=(FigureSpec("atm_iv", "decimal_vol", IV, skew("2026-06-03", "atm_iv")),),
)
WRONG = Question(
    id="wrong",
    date="2025-11-20",
    text="What was the 0DTE ATM IV on 2025-11-20, asked again?",
    purpose="test",
    status="answered",
    figures=ATM_IV.figures,
)


def submission(status: str, value: float = 0.0) -> str:
    numbers = [{"name": "atm_iv", "value": value, "unit": "decimal_vol", "figure_id": "x"}]
    return json.dumps(
        {
            "status": status,
            "answer": "fake",
            "numbers": numbers if status == "answered" else [],
            "missing_data": [],
        }
    )


FAKE_SUBMISSIONS = {
    ATM_IV.text: submission("answered", 0.2415),
    NO_SNAPSHOT.text: submission("cannot_answer"),
    WRONG.text: submission("answered", 0.30),
}


def fake_model(messages, tools, tool_choice, config):
    """Stands in for the agent: answers each question with a fixed fake submission."""
    question = messages[-1].text
    return ModelOutput.from_content(model="mockllm/model", content=FAKE_SUBMISSIONS[question])


def test_the_exam_runs_in_inspect_and_reports_the_net_score_and_counts(tmp_path):
    task = Task(
        dataset=dataset((ATM_IV, NO_SNAPSHOT, WRONG), FIXTURES),
        scorer=exam_grader(),
    )

    [log] = eval(
        task,
        model=get_model("mockllm/model", custom_outputs=fake_model),
        log_dir=str(tmp_path),
        display="none",
    )

    assert log.status == "success"
    metrics = {name: m.value for name, m in log.results.scores[0].metrics.items()}
    assert metrics == {"net_score": -1, "correct": 2, "incorrect": 1, "not_attempted": 0}
