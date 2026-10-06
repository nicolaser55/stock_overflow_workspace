# Setting up the Cursor agent (2026-10-06, autonomous mode)

Nicolas's decision (2026-10-06): the agent continues the research **autonomously, without asking for permission**. It may
only work in `C:\Users\nico\Desktop\stock_overflow_workspace` (add, modify, delete) and
`C:\Users\nico\Desktop\stock_overflow_data` (add new files and change or delete only those; never delete existing files).

## 1. What is in place

| File | Role | Loaded by Cursor |
|---|---|---|
| `AGENTS.md` | Orientation: the project, what to read first, autonomous mode | automatically, every Agent chat |
| `.cursor/rules/research-integrity.mdc` | Pre-registration, trial log, file scope, the "Never" list, parked decisions | always |
| `.cursor/rules/workflow.mdc` | Windows commands, running notebooks, recording, git branch `agent/research`, the working loop | always |
| `.cursor/rules/code-conventions.mdc` | Nicolas's code style | when `.py` / `.ipynb` / `.md` files are involved |
| `docs/RESEARCH_STATE_2026-10-06.md` | State, data seen, roadmap, **parked decisions** (§7), session log | read at the start of every chat |
| `docs/RESULTS_LOG.md` | All results | read at the start |
| `scripts/protect_data_folder.ps1` | Windows permissions that make existing data files undeletable (and raw data read-only) | run once by Nicolas |

**How autonomy works:** the agent never waits for you. Whatever only you can decide (new data sources such as dividends,
T-bills or VIX; evaluation on the untouched window; ideas outside the roadmap) is written to the "Parked decisions" table
in §7 of the research state, and the agent continues with the next allowed item. You answer parked decisions whenever you
want, in the chat or by editing the table.

## 2. What is enforced and what is only instructed

| Requirement | Enforced by | Strength |
|---|---|---|
| Existing data files cannot be deleted, moved or renamed | Windows permissions (`scripts/protect_data_folder.ps1`) | Real (against mistakes; the file owner could undo it, the rules forbid it) |
| Raw data and pipeline caches 00-05 cannot be modified | Windows permissions (same script) | Real (same caveat) |
| New files in the data folder can be changed and deleted | Windows permissions (deny entries are not inherited) | Real |
| Workspace files can be changed and deleted; history recoverable | git (agent works on branch `agent/research`, pushes it at session end) | Real (committed work) |
| The agent touches nothing outside the two folders | Rules only | **Instruction**: on Windows, Cursor's terminal sandbox is not available (its docs list macOS and Linux), so terminal commands run with your full user rights |
| Research integrity (pre-registration, no untouched window, no new data) | Rules only | Instruction |

If you want the folder restriction **enforced**, the only robust way on Windows is to run Cursor under a separate local
Windows user that has access to the two folders only (plus Python and the venv). That is more setup (Python, the Jupyter
kernel and the Cursor login have to work for that user); ask if you want the step-by-step.

## 3. One-time steps (on nicodesktop)

1. **Copy the update pack** over the workspace (nothing is deleted):

   ```
   Expand-Archive -Path <path to stock_overflow_agent_autonomy_20261006.zip> -DestinationPath $env:TEMP\so_auto -Force
   Copy-Item -Path $env:TEMP\so_auto\stock_overflow_workspace\* -Destination . -Recurse -Force
   New-Item -ItemType Directory -Force .cursor\rules | Out-Null
   Copy-Item -Path $env:TEMP\so_auto\stock_overflow_workspace\.cursor\rules\* -Destination .cursor\rules -Force
   git status
   git add -A
   git commit -m "agent autonomous mode: rules, parked decisions, data protection script"
   git push
   ```

2. **Back up what cannot be regenerated**, to a drive or cloud folder outside the computer: `store01_rawzone\` (the raw
   IBKR data and its pre-correction backup), `store04_experiments\trial_log.csv`, and the workspace's `records\`.
   Pipeline caches and experiment outputs can be regenerated.
3. **Protect the existing data files** (a few minutes; it ends with four test results that must all be True):

   ```
   powershell -ExecutionPolicy Bypass -File scripts\protect_data_folder.ps1
   ```

   Note: the protection applies to you too (you cannot delete those files in Explorer either). To undo it:
   `icacls "C:\Users\nico\Desktop\stock_overflow_data" /remove:d "$env:USERDOMAIN\$env:USERNAME" /T /C /Q`.
4. **Keep the computer awake** while the agent works (Settings → System → Power: sleep "Never" when plugged in), and keep
   Cursor open: the local agent stops when Cursor closes or the computer sleeps.

## 4. Cursor settings

- **Local Agent in the editor**, not a cloud agent (the data folder exists only on nicodesktop).
- **Run mode: "Run Everything"** (no approval prompts). On Windows the sandbox is not available, so the allowlist and
  auto-review modes would either prompt you or give no extra protection (a command like `python script.py` can do
  anything the script says, whatever the allowlist).
- **File-Deletion Protection: off** and **External-File Protection: off**; otherwise every deletion in the workspace and
  every operation on the data folder (outside the workspace) asks for approval. Deletions of existing data files are
  blocked by Windows instead (§3.3).
- **Model:** the strongest reasoning model in your plan, with thinking enabled if offered, the same model for a whole
  experiment; not the automatic router.
- **Spending:** autonomous sessions use a lot of model requests; set a monthly usage limit in Cursor's billing settings.

## 5. First message to the agent (paste as is, in a new Agent chat)

```
You are continuing the Stock Overflow research autonomously. Read AGENTS.md, then docs/RESEARCH_STATE_2026-10-06.md,
docs/RESULTS_LOG.md, experiments/README.md, experiments/exp02_stop_reentry/PROTOCOL.md, and the code of
so/core/reentry_simulation.py, so/core/evaluation.py, so/core/trial_log.py and experiments/exp03_ath_exit/rules.py.

Then, without waiting for me:
1. Switch to (or create) the branch agent/research and run the tests.
2. Close open item 1 of the research state (exp01 step 02 first-run counts at tag first-run-20261006) and record it.
3. Write in the chat, in a few lines, the goal, the success criterion, what has been learned, and what data must not be
   touched.
4. Work through the roadmap in order, starting with Step 0, following the working loop of workflow.mdc: plan, protocol,
   code and tests, pre-registration commit, runs, recording, commit. Park what only I can decide and keep going.
5. Stop only when the roadmap is done or every remaining item is blocked by a parked decision, then end the session as
   workflow.mdc says.
```

If the chat stops before the roadmap is done (context limit, Cursor restart), open a new Agent chat and send:
`Continue the research autonomously from the latest RESEARCH_STATE (session log, open items, parked decisions).`

## 6. What to review yourself

1. `git log agent/research`: the `preregister expNN` commits come **before** the validation runs of each experiment.
2. `docs/RESULTS_LOG.md`: numbers copied from notebook outputs; the prior-only path is the headline; experiments stopped
   when their rules say so; no "success" claim (only "candidate result pending review").
3. §7 of the research state: the parked decisions waiting for you.
4. When satisfied, merge `agent/research` into `main` (or ask the agent to open a pull request).
