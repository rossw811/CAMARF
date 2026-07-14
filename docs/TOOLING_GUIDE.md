# Tooling Guide — Installed Plugins, Skills, and MCP Servers

Added 2026-07-13. This documents what's installed in this Claude Code environment,
when each is actually useful for CAMARF, and the exact prompt/command to invoke it.
Not every installed thing gets used every session — this is a reference, not a
checklist to run through each time. `CLAUDE.md`'s "Recommended Plugins / Tools"
section has the short list of the highest-value ones for daily CAMARF work; this
file is the full inventory, with an exact invocation for every entry.

## How to invoke

- **Slash commands** (`/name` or `/name:subskill`) — typed directly in the session.
- **Skills** — most skills also auto-trigger based on context (e.g. mentioning
  "chart" triggers `dataviz`), but the exact prompts below work as explicit
  invocations regardless of whether auto-trigger would have caught it.
- **MCP servers** — background tools Claude can call without a slash command;
  currently minimal in this environment (only `findskills`, used internally to
  discover skills — nothing CAMARF-specific is wired in as an MCP server yet).

---

## Confirmed installed plugins (from `~/.claude/plugins/installed_plugins.json`)

| Plugin | When to use on CAMARF | Exact prompt / command |
|---|---|---|
| `code-review` | After any nontrivial change to `data.py`/`analysis.py`/`backtest.py`/`ml.py`, before calling it done | `/code-review` — reviews the current diff. `/code-review ultra` — deep multi-agent cloud review before a big milestone (e.g. before treating a PAPER.md reconciliation pass as final) |
| `context7` | Before writing/debugging code against yfinance, statsmodels, arch, scikit-learn, or xgboost, where exact current version behavior matters more than training-data knowledge | No slash command — say "check the current docs for `statsmodels.tsa.stattools.coint`" (or whichever library/function) and Claude will reach for context7 automatically |
| `feature-dev` | Genuine new-feature builds (a new `research/` module, a `backtest.py` STORM variant) — not bug fixes | `/feature-dev:feature-dev build a [feature name] that [does X]` |
| `claude-md-management` | Periodically, to keep `CLAUDE.md` from drifting stale as the project grows | `/claude-md-management:revise-claude-md` — updates it with this session's learnings. Or ask: "audit CLAUDE.md for staleness" to trigger `claude-md-improver` |
| `skill-creator` | If a recurring CAMARF pattern emerges worth packaging (e.g. "diagnose a `data.py` log" as a one-shot skill) | `/skill-creator:skill-creator create a skill that [does X]` |
| `agent-sdk-dev` | Not relevant to CAMARF (CAMARF isn't an agent-SDK application) | N/A |
| `draw-io` | Near v1 shipment, for a pipeline/architecture diagram — not a current priority | "Create a draw.io architecture diagram of CAMARF's data.py → analysis.py → backtest.py pipeline" |
| `improve` | Periodic "what's the highest-leverage next fix" gut-check, distinct from this project's own bug-sweep/adversarial-review work | `/improve:improve` — read-only audit, produces a prioritized plan for another agent to execute |
| `last30days` | Only if researching very recent market sentiment/discourse (not CAMARF's academic literature work — use `/storm` for that) | `/last30days:last30days <topic>` |
| `obsidian` | Not yet used on CAMARF. Relevant if session notes or the research backlog move into an Obsidian vault — noted for later per Ross's interest, not a current need | `/obsidian:obsidian-cli <command>` for vault operations; ask directly for `.canvas`/`.base` file work |
| `storm` | Already in active use this session for market-structure/literature-convergence research (Phase 12 of the current plan) | `/storm:storm <specific research question>` — fully cited, multi-perspective report. `/storm:storm-brief <question>` — faster, uncited, when speed beats citations |
| `superpowers` | Where a specific sub-skill adds a concrete checklist Claude wouldn't otherwise follow (TDD discipline, systematic debugging) — not reflexively on every task | `/superpowers:systematic-debugging` when stuck on a real bug; `/superpowers:test-driven-development` before writing new production code; `/superpowers:brainstorming` before a genuinely new feature design |
| `claude-code-setup` | Run periodically (e.g. once per major project phase) to check whether CAMARF is missing a useful automation | Invoke the skill directly: "run the claude-automation-recommender on this project" (already run once, 2026-07-13 — see Development.md) |
| `explanatory-output-style` | Optional — CAMARF's `CLAUDE.md` already asks for direct, non-hedging answers; evaluate only if response tone ever feels off | `/output-style explanatory` to switch, `/output-style default` to revert |
| `github` | Likely useful once CAMARF's real GitHub remote (`github.com/rossw811/CAMARF`) is actively used for PR/issue workflows — not yet exercised this session, and `gh` CLI isn't installed locally (a prerequisite gap) | Install `gh` CLI first; then standard `gh pr`/`gh issue` commands become available to Claude directly via Bash |

## Built-in skills (not separately "installed," always available)

| Skill | When to use on CAMARF | Exact prompt / command |
|---|---|---|
| `graphify` | CAMARF has a `graphify-out/` directory already — use for architecture questions before raw grep, per `CLAUDE.md`'s own instruction | `graphify query "<question>"` for architecture questions, `graphify path "<A>" "<B>"` for relationships, `graphify explain "<concept>"` for a focused concept. Run `graphify update .` after code changes to keep it current |
| `deep-research` | Open-ended external research questions outside CAMARF's own codebase (e.g. verifying a citation's real content) | Just ask the question directly with enough specificity — the skill triggers automatically on "deep, multi-source, fact-checked research" requests |
| `dataviz` | Before building `report.py`'s new figures (Phase 16 of the current plan) | Read automatically before Claude writes any chart code — no separate invocation needed, just ask for the chart/figure |
| `artifact-design` | If any CAMARF finding ever gets published as an interactive web artifact rather than a static PAPER.md figure | Triggers automatically when Claude is about to publish an Artifact |
| `verify` | Less relevant to CAMARF (`run_verify_suite.py` already serves this role) | "Verify that [this change] actually works end-to-end" |
| `simplify` | After a research module is verified and working, before considering it "done" — quality pass, not a bug hunt | `/simplify` on the current diff |
| `security-review` | Low relevance to CAMARF — skip unless a specific concern arises | `/security-review` |
| `fewer-permission-prompts` | Once CAMARF's common command patterns stabilize, to reduce friction | `/fewer-permission-prompts` |
| `update-config` | For any "always do X when Y happens" automation request — memory/CLAUDE.md notes can't enforce this, only hooks can | Ask directly: "add a hook that runs `run_verify_suite.py` after any edit to `research/*.py`" |
| `keybindings-help` | Not CAMARF-specific | Ask directly: "rebind [key] to [action]" |
| `loop` / `schedule` | Could run a periodic (e.g. daily) automated bug-sweep or verification pass once CAMARF is more stable — not currently set up | `/loop 30m /run_verify_suite` (interval self-paced if omitted) or `/schedule` for cron-style recurring runs |
| `claude-api` | Not relevant to CAMARF (a research pipeline, not an LLM application) | N/A |

---

## Not yet exercised on CAMARF, worth knowing about

- **`obsidian`** — Ross wants to use this at some point; no current CAMARF integration.
- **`/code-review ultra`** — the deep multi-agent cloud review variant; not yet run
  on CAMARF's current diff (a large one, given this session's scope) — worth
  running once the current round of work stabilizes. Prompt: `/code-review ultra`.
- **`gh` CLI** — not installed; needed before the `github` plugin's commands are
  actually usable for PR/issue workflows on the real `github.com/rossw811/CAMARF`
  remote.

## Explicitly not recommended

- **`ponytail`** (if ever offered) — its "write minimum code, avoid
  over-engineering" philosophy conflicts with CAMARF's verify-everything,
  no-bandaid-fixes discipline (`CLAUDE.md`'s own note, predates this file).
