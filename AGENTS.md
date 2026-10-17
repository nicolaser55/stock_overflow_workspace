# AGENTS.md: Stock Overflow research workspace

You are continuing a thesis-style quantitative research project for Nicolas: can a long-only, unlevered strategy on SPY
beat **buy-and-hold's total return** after realistic costs, out of sample? You act as a rigorous research collaborator,
not as an optimizer chasing a good number.

## Read first, every new chat (in this order)

1. `docs/RESEARCH_STATE_<latest date>.md`: where the research stands, what data has been seen, the roadmap, open items.
2. `docs/RESULTS_LOG.md`: every result so far, including failures.
3. `experiments/README.md`: the experiment registry and how to add an experiment.
4. The `PROTOCOL.md` of the experiment you work on (and `experiments/exp02_stop_reentry/PROTOCOL.md` as the reference
   walk-forward design).
5. `README.md` §4-§8: machines, data folders, discipline, tests, conventions.

The rules in `.cursor/rules/` always apply: `research-integrity.mdc` (what you may and may not do, file scope, and what
to park for Nicolas), `workflow.mdc` (how to run things on this Windows machine and what to record), `code-conventions.mdc` (style).

## The project in five lines

- Code: `so/` (shared library), `pipeline/` (shared data notebooks 00-06), `experiments/expNN_<name>/` (one folder per
  experiment: `PROTOCOL.md`, `config.py`, code, `stepNN_*.ipynb`), `tests/`, `docs/`, `records/`.
- Data (never in git): `C:/Users/nico/Desktop/stock_overflow_data/` (`so.paths`, override with `SO_DATA_PATH`).
- Every experiment run is logged in `store04_experiments/trial_log.csv` (never edit it) and reported in
  `docs/RESULTS_LOG.md` the same day.
- exp01 to exp07, exp12 and exp13 are protocol 2.0. exp08 and the skipped exp09–exp11 were removed from this tree on
  2026-10-16; their results stay in `docs/RESULTS_LOG.md` and their code at tag `pre-port-20261012`. The VIX line is
  closed (exp13: E1M1 IS NOT ROBUST).
- Every series a strategy reads is registered in `so.core.point_in_time` and read through `DataContext`
  (`docs/DATA_SOURCES.md`). A value may be used at a decision only when its `available_ts` is at or before that decision.
  Labels may look forward; a model trained at time t uses only rows whose `label_known_ts` is before t.
- The evaluation design is the rolling 12-month holdout (`so.core.holdout`, `records/holdout_windows.csv`). Rule 1 of
  `research-integrity.mdc`: never read the registered window for exploration, validation or any decision; never set
  `SO_HOLDOUT_PATH` or `SO_HOLDOUT_EVALUATION_TOKEN`; never run
  `scripts/holdout_window.py` or `scripts/holdout_evaluate.py`. Tests under `tests/` may set those variables to
  temporary values on synthetic data only. If no window is registered, development notebooks must refuse to run.
- Next is parked for Nicolas: write-up of the negative result, then text data. Calibration re-runs of exp05 and exp06
  under the new split, as new versions, are proposed and waiting for Nicolas.
- **You work autonomously** (Nicolas, 2026-10-06): never ask for permission or wait for an answer. Decisions only Nicolas
  can make are parked in §7 of the research state and you continue with the next allowed item.
- Stay inside the workspace and the data folder; never delete, move or rename the data folder's existing files,
  and change existing ones only as `research-integrity.mdc` ("File scope") allows (e.g. the trial log is only appended to). Commit on the branch `agent/research`.
- Nicolas's instructions in the chat override this file, except the "Never" rules of `research-integrity.mdc`, which he
  must change in the file himself.
