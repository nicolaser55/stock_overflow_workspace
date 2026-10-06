# Setting up the Cursor agent (2026-10-06)

## 1. What is in place

| File | Role | Loaded by Cursor |
|---|---|---|
| `AGENTS.md` | Orientation: what the project is, what to read first | automatically, every Agent chat |
| `.cursor/rules/research-integrity.mdc` | Pre-registration, trial log, untouched data, **when to stop and ask** | always |
| `.cursor/rules/workflow.mdc` | Windows/PowerShell commands, running notebooks, recording results, committing, ending a session | always |
| `.cursor/rules/code-conventions.mdc` | Your code style | when `.py` / `.ipynb` / `.md` files are involved |
| `docs/RESEARCH_STATE_2026-10-06.md` | Where the research stands, data seen, roadmap (Step 0, exp04-exp07, VIX, text), open items, session log | read by the agent at the start of every chat |
| `docs/RESULTS_LOG.md` | All results, now including the first run of exp01-exp03 | read at the start |

Chats do not remember each other. The research state document is the agent's memory: it updates it at the end of every
session, and every new chat starts by reading it.

## 2. Install (on nicodesktop)

1. Copy the update pack over the workspace (nothing is deleted):

   ```
   Expand-Archive -Path <path to stock_overflow_agent_setup_20261006.zip> -DestinationPath $env:TEMP\so_agent -Force
   Copy-Item -Path $env:TEMP\so_agent\stock_overflow_workspace\* -Destination . -Recurse -Force
   New-Item -ItemType Directory -Force .cursor\rules | Out-Null
   Copy-Item -Path $env:TEMP\so_agent\stock_overflow_workspace\.cursor\rules\* -Destination .cursor\rules -Force
   Copy-Item -Path $env:TEMP\so_agent\stock_overflow_workspace\.gitignore -Destination . -Force
   git status
   ```

2. Commit: `git add -A; git commit -m "agent setup: AGENTS.md, .cursor/rules, research state, first-run results"; git push`.
3. In Cursor: open the workspace folder, then **Cursor Settings → Rules** and check that the three project rules are
   listed (and that `AGENTS.md` is picked up).

## 3. Cursor settings

- **Use the local Agent in the editor, not a cloud/background agent.** The data folder exists only on nicodesktop.
- **Model:** pick the strongest reasoning model in your plan's model picker, with thinking enabled if it is offered, and
  keep the **same model for a whole experiment** (consistency of judgment matters more than speed). Avoid the automatic
  model router for research sessions. A faster, cheaper model is fine for purely mechanical edits.
- **Terminal commands:** let the agent run commands, but keep approval on for anything that deletes, moves files, pushes,
  or installs packages (the rules forbid these anyway; the setting is a second lock).
- **Long runs:** the rules tell the agent to start long notebooks in the background with a log and poll it, so a 1-hour
  walk-forward does not block or time out the chat.

## 4. First message to the agent (paste as is)

```
You are continuing the Stock Overflow research. Read AGENTS.md, then docs/RESEARCH_STATE_2026-10-06.md,
docs/RESULTS_LOG.md, experiments/README.md, experiments/exp02_stop_reentry/PROTOCOL.md, and the code of
so/core/reentry_simulation.py, so/core/evaluation.py, so/core/trial_log.py and experiments/exp03_ath_exit/rules.py.

Then:
1. Run the tests (venv-main\Scripts\python.exe tests\run_all_tests.py) and report the result.
2. Close open item 1 of the research state: check that the first-run notebook of exp01 step 02 at git tag
   first-run-20261006 shows test_count 5628, train_pass_count 174 and signal_count 4, and record the outcome in
   docs/RESULTS_LOG.md.
3. Summarize in your own words, in a few lines, the goal, the success criterion, what has been learned, and what data
   must not be touched, so I can check that you understood.
4. Propose a detailed plan for Step 0 of the roadmap (continuous replay, episode scorecard, annualized log-excess
   bootstrap, fractional exposure): files, functions with signatures, tests, and how you will prove that exp01-exp03
   numbers do not change. Do not write code yet; wait for my OK.
```

## 5. Later messages (templates)

- **Continue:** `Continue with the next item of the roadmap in the latest RESEARCH_STATE. Start with the protocol and the
  plan; commit the pre-registration before any validation run.`
- **Review a protocol before it runs:** `Show me the PROTOCOL.md of expNN and the candidate grid; list what could make
  the result look better than it is.`
- **After a run:** `Explain the results of expNN step NN mathematically and in plain words, compare them with buy-and-hold
  and the baselines, and say whether a stopping rule fires.`
- **End of session:** `End the session: update the research state (session log and open items), the results log and the
  registry, snapshot the trial log, commit, and summarize.`

## 6. What to review yourself (about 10 minutes per experiment)

1. The **pre-registration commit** (`preregister expNN`): question, grid, baselines, stopping rule. Is anything chosen
   with hindsight? Is the uninformed baseline there?
2. The **results log entry**: are the numbers copied from the notebook outputs? Is the prior-only path the headline? Is
   the experiment stopped when its rule says so?
3. `git log` / `git diff` on `so/`: shared code changes come with tests, and the exp01-exp03 reproduction numbers still
   hold.
4. Anything the agent stopped to ask (data sources, test windows, new versions): those decisions are yours.
