# Answers are marked +1 correct, 0 cannot answer, -3 wrong, with no self-reported confidence

Status: accepted (2026-10-14)

Plain right/wrong marking rewards guessing, and models' self-reported confidence is badly calibrated. SimpleQA grades correct, incorrect and not attempted. Kalai et al. (2025) show that a penalty of t/(1-t) for a wrong answer makes "answer only when more than t confident" the best strategy, if the rule is stated to the model.

**Decision.** Net score is +1 per correct answer, 0 per `cannot_answer` or not attempted, -3 per incorrect answer (t = 0.75). The rule is stated in the agent's instructions. Unanswerable questions score +1 for `cannot_answer`. No confidence field.

## Considered options

- Plain accuracy: rejected; rewards bluffing.
- A self-reported confidence field: rejected; models overstate it by about 30 points.

## Consequences

- The exam reports correct, incorrect and not attempted counts beside the net score.

## Why

*Lalit writes this section, in plain words, as part of #7. Answer: why -3 for a wrong answer in a finance setting, and what would -1 change?*
