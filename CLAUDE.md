# CLAUDE.md

This is Lalit's learning repo. The point is that Lalit understands every line, so how work is done
here matters more than speed. Read [docs/roadmap.md](docs/roadmap.md) before anything else.

## Rules

- **`learn` tickets are Lalit's to write.** Do not write their implementation code, even when
  asked casually mid-session; explain, point at the concept, review. Tests and code for `glue`
  tickets are fine, and feature-loop builds those.
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

These become real once #2 (repo skeleton) lands.

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
