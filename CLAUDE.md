# CLAUDE.md

This is Lalit's learning repo. The point is that Lalit understands every line, so how work is done
here matters more than speed. Read [docs/roadmap.md](docs/roadmap.md) before anything else.

## Rules

- **`learn` tickets are written together.** Claude writes the code in chat in small pieces (one
  test, then the code that passes it), each with the file it goes in, what every line does and
  where the pattern comes from (linked source). No check questions; Lalit asks when something
  is unclear. Lalit types it into the file and runs it, or, once Lalit says a piece is
  understood, tells Claude to write it into the files directly.
- **`glue` tickets:** in P1, Claude builds each one directly as a PR into `main` that Lalit skims
  and merges; feature-loop's orchestrator is kept for later phases.
- **Every `glue` PR carries a walkthrough** so nothing is a black box: what was built, file by
  file in plain words; why each choice was made; the concepts it touches with resources; and a
  ready-to-paste ChatGPT prompt (below).
- **Doubts go to ChatGPT, to save Claude usage.** Lalit has a ChatGPT Go project connected to
  this GitHub repo. With every walkthrough, and at the start of every `learn` ticket, give a
  fenced prompt for it that names the repo, the issue or PR, the exact files and docs to read
  (`CONTEXT.md`, the spec, the decision records), what to explain at a beginner's level, and, for
  `learn` tickets, an instruction to explain the code written so far and quiz on it.
- **Teach when a concept comes up:** explain it in chat, then list every genuinely good video,
  article and official doc (ranked, "start here" first; not a fixed one of each) in the ticket
  issue under "Concepts". Not `/study` sessions, not separate notes.
- **Each phase starts with research** (`docs/research/<phase>-references.md`): how well-built
  projects did each part, before the design is fixed.
- **Reviews explain, they do not fix.** Name the problem, the concept behind it and where to read
  more. Write the fix only if Lalit asks for it twice.
- **ADRs:** draft the context and options; leave the "why" paragraph for Lalit to write.
- **Raw Databento data and credentials never enter git.** See the data rules in the roadmap.
- No Claude attribution in commits or PRs.

## Where things are

- Plan and phases: `docs/roadmap.md`
- Domain terms: `CONTEXT.md` (from P1 design)
- Design docs and ADRs: `docs/design/`, `docs/design/decisions/`
- Work state: GitHub issues on `lalitkarthik/options-agent`

<!-- feature-loop:start -->
## Feature workflow

Changes that add or alter behaviour go through the feature loop, which builds only `glue` tickets (`learn` tickets are Lalit's; see `docs/agents/issue-tracker.md`): `/feature-loop plan` (it starts
the build itself when you approve), and `/feature-loop audit` checks the built product.
Documentation-only changes and one-line fixes take a branch and a PR with no spec. Phases, the
wave rule, the models, the context budget (hand off at 40%, never past 45%) and the git rules are
in `~/.claude/skills/feature-loop/workflow.md`. The build merges its own PR into `main` when
every ticket is closed, the suite is green and the user-flow check passed; otherwise the PR stays
open for you.

Issues live on GitHub at `lalitkarthik/options-agent`, driven with `gh`: a feature is an issue labelled `feature`,
its tickets are sub-issues labelled `ticket` with native blocked-by edges. See
`docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md`.

### Commands

Real since #2 (repo skeleton).

| Step | Command |
| --- | --- |
| Set up a fresh worktree | `uv sync` |
| Typecheck | `none` |
| Lint and format check | `uv run ruff check . && uv run ruff format --check .` |
| Run one test file | `uv run pytest <path>` |
| Run the full test suite | `uv run pytest` |
| Run the app | `none` |
| App URL | `none` |

### Docs

| Path | Holds | Written when |
| --- | --- | --- |
| `CONTEXT.md` | the glossary: one line per term | the moment a term is first used |
| `docs/design/` | the project design, when there is one: overview, part pages, grilling log, and `build-order.md` (every feature, in build order); the source of truth it covers | `/feature-loop design`; `/feature-loop gaps` |
| `docs/decisions/NNNN-<slug>.md` | one decision record each (in `docs/design/decisions/` when there is a design) | when a decision is locked in |
| `docs/specs/<slug>.md` | one spec per feature, with its Assumptions and a `Status:` line | planning; status updated at the build's end |
| `docs/research/<topic>.md` | research notes with sources | planning; `/feature-loop gaps` |
| `docs/audits/<yyyymmdd>.md` | one ledger per audit run: every finding and its status | `/feature-loop audit` |
| `CHANGELOG.md` | what changed for the user, newest first | the end of a build or an audit |

Reading rules for these files are in `docs/agents/domain.md`. Design pages, specs and research
notes are written in the house format of `~/.claude/skills/feature-loop/prompts/docs-style.md`.
<!-- feature-loop:end -->

## Agent skills

### Issue tracker

GitHub Issues in lalitkarthik/options-agent, driven with `gh`; each phase is a feature issue with its tickets as sub-issues, every ticket `learn` or `glue`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix), plus feature, ticket, in-progress, audit, learn and glue. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at the root, the design in `docs/design/`, decisions in `docs/design/decisions/`. See `docs/agents/domain.md`.
