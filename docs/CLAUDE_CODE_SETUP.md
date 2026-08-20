# Claude Code Setup for CAMARF — Comprehensive Guide

This is the complete setup: installation, authentication, plugins, agents,
project configuration, and safety practices specific to working on CAMARF
(and the live paper-trading system) with Claude Code.

---

## 1. Prerequisites

- A Claude subscription (Pro, Max, Team, or Enterprise) — Pro at $20/mo is
  the simplest option and uses your existing Claude account. Alternatively
  an API key for usage-based billing.
- Windows 10/11. Native install is recommended — **WSL2 is NOT required**
  despite what some outdated guides say. Claude Code has run natively on
  Windows since late 2025.
- Git for Windows is *recommended* (not required) so Claude Code can use
  its Bash tool. Without it, Claude Code falls back to PowerShell as the
  shell tool, which works fine for this project.

---

## 2. Installation (Native Windows — Recommended Path)

Open PowerShell (not CMD — check your prompt shows `PS C:\` not just `C:\`)
and run:

```powershell
irm https://claude.ai/install.ps1 | iex
```

This downloads and installs the Claude Code binary and adds it to your PATH.

**Alternative via winget:**
```powershell
winget install Anthropic.ClaudeCode
```
Advantage: future updates via `winget upgrade Anthropic.ClaudeCode`.

**Alternative via direct download:** claude.ai/download → Windows installer
→ double-click.

After installing, **close and reopen your terminal** (PATH needs to refresh),
then verify:
```powershell
claude --version
```

If you see `claude : The term 'claude' is not recognized` after reopening,
manually add to PATH:
```powershell
[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;$env:USERPROFILE\.local\bin", [EnvironmentVariableTarget]::User)
```
Then reopen the terminal again.

### Optional: WSL2 (only if you want OS-level sandboxing)

Sandboxing — isolating Claude Code so it can only touch specific files/network
— currently only works on macOS/Linux/WSL2, not native Windows. If you want
that extra isolation layer (reasonable given this project touches a live
trading system), WSL2 is the path. Otherwise, skip it — native is simpler
and sufficient for CAMARF's research/backtesting work.

---

## 3. Authentication

```powershell
claude
```
On first run it prompts you to authenticate — follow the terminal prompts to
connect your Claude Pro/Max account, or provide an API key.

---

## 4. Project Setup

```powershell
cd C:\Users\RossW\Projects\CAMARF
claude
```

Claude Code reads `CLAUDE.md` automatically from the project root at the
start of every session — this is already drafted and should be saved at
`C:\Users\RossW\Projects\CAMARF\CLAUDE.md`.

**Important — initialize git if you haven't already**, both for Claude Code's
diff/commit features and as a safety net (see Section 7):
```powershell
git init
git add .
git commit -m "Initial commit before Claude Code"
```

---

## 5. Plugins and Marketplaces

Claude Code plugins come from "marketplaces" — GitHub repos that distribute
collections of plugins. You need to add a marketplace before installing
plugins from it.

### Add the official Anthropic marketplace
```
/plugin marketplace add anthropics/claude-plugins-official
```

### Install the recommended plugins for CAMARF

```
/plugin install claude-md-management@claude-plugins-official
/plugin install skill-creator@claude-plugins-official
```

**`feature-dev`** is bundled directly with Claude Code itself (from the
`anthropics/claude-code` repo's own plugin set, separate from the
`claude-plugins-official` marketplace). Add that marketplace too:
```
/plugin marketplace add anthropics/claude-code
/plugin install feature-dev@claude-code
```

If either install command reports the plugin isn't found, refresh first:
```
/plugin marketplace update claude-plugins-official
```
then retry. After any install, run:
```
/reload-plugins
```
to make the new skills available in the current session.

**`context7`** — you already have this installed. It's an MCP-based
documentation lookup tool; once installed it's available automatically,
invoked either by you explicitly or by Claude recognizing it's relevant
(e.g. "check context7 for current yfinance docs").

**`graphify`** (added since this guide was first written — now an
established, actively-used tool, not optional) — turns the codebase into
a queryable knowledge graph (`graphify-out/graph.json`), used for
architecture questions and cross-file relationship queries. Install via
`uv tool install graphifyy` (needs `uv`: `pip install uv` first if not
already present), then `graphify claude install` from the project root to
wire the CLAUDE.md section + PreToolUse hook. See the `## graphify`
section in `CLAUDE.md` for the query/path/explain usage convention.

**This list is no longer complete** (added as a note 2026-08-20, not rewritten in place — this
guide's job is "how to install from scratch," not "the current full inventory"). Several more
plugins/CAMARF-specific skills/subagents/hooks have been added since this section was written —
`storm`, `superpowers`, `last30days`, `code-review`, plus CAMARF-specific tools under
`.claude/skills/`/`.claude/agents/`/`.claude/hooks/` (the `council-*` 5-lens review panel,
`adversarial-reviewer`, `premortem`, `verify-new-module`, `diagnose-run-log`,
`guard_manifest.py`). See `docs/TOOLING_GUIDE.md` for the full, kept-current inventory with exact
invocations — this section only covers the handful installed at initial setup time.

### Explicitly do NOT install

**`ponytail`** — verified real, but its "minimize code written, flag
over-engineering" philosophy directly conflicts with this project's
verify-everything, no-bandaid-fixes discipline. Skip it.

### Optional, for later (noted in DEVELOPMENT.md, not urgent)

**`draw.io`** (`little-hands/claude-drawio-skill`) — for architecture
diagrams, worth adding nearer v1 shipment:
```
/plugin marketplace add little-hands/claude-drawio-skill
```

### Security scanning new plugins before install

**`SkillSpector`** (NVIDIA, `github.com/nvidia/skillspector`) — a security
scanner for AI agent skills/plugins, run separately (not itself a Claude
Code plugin). Research cited in its README found 26.1% of scanned skills
had at least one vulnerability, 5.2% showed likely malicious intent. Good
practice going forward: scan any *new* third-party plugin before installing
it, beyond the ones already vetted in this guide.
```bash
git clone https://github.com/NVIDIA/skillspector.git
cd skillspector
uv venv .venv && source .venv/bin/activate  # or python3 -m venv .venv
make install
skillspector scan <path-or-url-to-new-plugin>
```

---

## 6. Understanding Agents (via feature-dev)

`feature-dev` bundles three specialist agents that activate automatically
within its workflow:

- **code-explorer** — surveys the existing codebase before any new feature
  work starts, building context on conventions and architecture already in
  place (relevant: it should read `data.py`/`analysis.py`'s existing
  patterns before proposing how `ml.py` should be structured)
- **code-architect** — designs the approach before implementation begins
- **code-reviewer** — reviews the implementation against the design and
  codebase conventions

Invoke the workflow with:
```
/feature-dev
```
when starting genuinely new feature work — this is the right tool for
`macro.py`, `ml.py`, `backtest.py`, `analyzer.py`, not for the bug-fixing
work that's dominated the project so far (use plain conversation + your own
verification discipline for that, as we've been doing).

---

## 7. Safety Practices — Read This Before Your First Real Session

Claude Code has direct, autonomous filesystem access. Documented real-world
failure modes worth taking seriously, especially given this project's
connection to a live paper-trading system with real financial consequences:

- **Commit to git before starting any session.** This is your actual safety
  net — if something goes wrong, you can always diff against or revert to
  the last commit.
- **Review diffs before accepting.** Claude Code's `/diff` command shows an
  interactive view of all changes in a session. Use it as a checkpoint
  after any series of edits, before moving on.
- **Never let it run unattended on the live trading system.** CAMARF
  research/backtesting is lower-stakes than `paper_trader.py` or anything
  touching live IBKR order execution. Treat those with extra caution —
  review every change manually, every time, no exceptions.
- **Watch for correction loops.** A documented failure mode: the agent
  enters an endless correction loop where each fix introduces a new
  regression. If you see this starting (which, candidly, happened in this
  project's chat-based debugging too, e.g. the yfinance session saga), stop
  and ask for raw diagnostic evidence rather than letting it keep guessing
  — same discipline as documented in `CLAUDE.md`'s "Working Style" section.
- **Be aware of quota sharing.** Claude Code and claude.ai chat share the
  same rolling 5-hour subscription quota on Pro/Max plans. Heavy use in one
  surface reduces what's available in the other during that window.
- **A concrete example of this discipline, actually implemented, not just discussed** (added
  2026-08-20): `.claude/hooks/guard_manifest.py` is a `PreToolUse` hook that blocks direct
  Write/Edit to `confirmed_pairs_manifest.json` — built after that exact file was contaminated
  with test data twice (BUG-D63). A real, working example of turning a repeated real incident
  into an automated guardrail rather than just a documented rule to remember.

---

## 8. First Session — Bootstrap Prompt

Once installed and configured, your first message in a new Claude Code
session on this project should be something like:

> Read CLAUDE.md and the most recent Session entry + "Next Session" block
> in DEVELOPMENT.md. Confirm you understand the current project state
> before we start.

This forces the context-loading step explicitly rather than assuming it
happened, and gives you a chance to confirm the new session actually has
working understanding before you hand it real tasks.

---

## 9. Quick Reference — Common Commands

| Command | Purpose |
|---|---|
| `/plugin marketplace add <repo>` | Add a plugin marketplace |
| `/plugin install <name>@<marketplace>` | Install a specific plugin |
| `/reload-plugins` | Activate newly installed plugins in current session |
| `/feature-dev` | Start the guided feature development workflow |
| `/diff` | Review all changes made in the session so far |
| `/compact` | Compress conversation history when context gets long — do this proactively between major phases, not just when forced |
| `/memory` | View/edit Claude Code's persistent project memory |
| `/doctor` | Check Claude Code's own health/configuration |
| `claude --version` | Confirm installed version |
| `claude update` | Manually update (native installs auto-update in background) |
