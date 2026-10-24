import json
from pathlib import Path

import pytest
from inspect_ai import Task, eval
from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
from inspect_ai.tool import ToolCall

from options_agent.exam import dataset, exam_grader, exam_task, options_agent, results
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


SKEW_CALL = {"date": "2025-11-20", "expiry": "2025-11-20"}
ATM_IV_NUMBER = {
    "name": "atm_iv",
    "value": 0.2415,
    "unit": "decimal_vol",
    "figure_id": "skew:2025-11-20:2025-11-20:atm_iv",
}
ANSWERED = {"status": "answered", "answer": "24%", "numbers": [ATM_IV_NUMBER], "missing_data": []}
CANNOT = {"status": "cannot_answer", "answer": "No data.", "numbers": [], "missing_data": ["day"]}


def fake_claude(messages, tools, tool_choice, config):
    """Stands in for Claude behind the bridge: one get_skew call, then submit_answer."""
    if not any(message.role == "tool" for message in messages):
        return ModelOutput.for_tool_call("mockllm/model", "get_skew", SKEW_CALL)
    return ModelOutput.for_tool_call("mockllm/model", "submit_answer", ANSWERED)


def test_the_agent_answers_a_question_through_the_bridge_and_is_graded(tmp_path):
    task = Task(
        dataset=dataset((ATM_IV,), FIXTURES),
        solver=options_agent(FIXTURES),
        scorer=exam_grader(),
    )

    [log] = eval(
        task,
        model=get_model("mockllm/model", custom_outputs=fake_claude),
        log_dir=str(tmp_path),
        display="none",
    )

    assert log.status == "success"
    metrics = {name: m.value for name, m in log.results.scores[0].metrics.items()}
    assert metrics == {"net_score": 1, "correct": 1, "incorrect": 0, "not_attempted": 0}
    assert log.samples[0].scores["exam_grader"].metadata == {"stop": "submitted"}


def test_five_trials_report_the_per_trial_averages_and_pass_hat_5(tmp_path):
    submits = {ATM_IV.text: 0}

    def right_four_times_in_five_on_atm_iv(messages, tools, tool_choice, config):
        question = next(message for message in messages if message.role == "user").text
        if question == NO_SNAPSHOT.text:
            return ModelOutput.for_tool_call("mockllm/model", "submit_answer", CANNOT)
        if not any(message.role == "tool" for message in messages):
            return ModelOutput.for_tool_call("mockllm/model", "get_skew", SKEW_CALL)
        submits[question] += 1
        submission = CANNOT if submits[question] == 5 else ANSWERED
        return ModelOutput.for_tool_call("mockllm/model", "submit_answer", submission)

    [log] = eval(
        exam_task((ATM_IV, NO_SNAPSHOT), FIXTURES),
        model=get_model("mockllm/model", custom_outputs=right_four_times_in_five_on_atm_iv),
        log_dir=str(tmp_path),
        display="none",
    )

    assert log.status == "success"
    assert [score.reducer for score in log.results.scores] == ["mean", "pass_k_5"]
    table = results(log)
    assert table["net score"] == pytest.approx(1.8)
    assert table["correct"] == pytest.approx(1.8)
    assert table["incorrect"] == 0
    assert table["not attempted"] == pytest.approx(0.2)
    assert table["pass^5"] == 0.5
    assert table["cost per question ($)"] == 0
    assert table["time per question (s)"] > 0


def test_the_message_limit_stops_a_runaway_agent_and_it_is_not_attempted(tmp_path):
    def six_calls_every_turn(messages, tools, tool_choice, config):
        calls = [
            ToolCall(id=f"call_{len(messages)}_{n}", function="list_dates", arguments={})
            for n in range(6)
        ]
        message = ChatMessageAssistant(content="", tool_calls=calls)
        return ModelOutput.from_message(message, stop_reason="tool_calls")

    [log] = eval(
        exam_task((ATM_IV,), FIXTURES),
        model=get_model("mockllm/model", custom_outputs=six_calls_every_turn),
        log_dir=str(tmp_path),
        display="none",
    )

    assert [sample.limit.type for sample in log.samples] == ["message"] * 5
    assert results(log)["not attempted"] == 1
