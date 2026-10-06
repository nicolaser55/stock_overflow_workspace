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

The rules in `.cursor/rules/` always apply: `research-integrity.mdc` (what you may and may not do, and when to stop and ask
Nicolas), `workflow.mdc` (how to run things on this Windows machine and what to record), `code-conventions.mdc` (style).

## The project in five lines

- Code: `so/` (shared library), `pipeline/` (shared data notebooks 00-06), `experiments/expNN_<name>/` (one folder per
  experiment: `PROTOCOL.md`, `config.py`, code, `stepNN_*.ipynb`), `tests/`, `docs/`, `records/`.
- Data (never in git): `C:/Users/nico/Desktop/stock_overflow_data/` (`so.paths`, override with `SO_DATA_PATH`).
- Every experiment run is logged in `store04_experiments/trial_log.csv` (never edit it) and reported in
  `docs/RESULTS_LOG.md` the same day.
- exp01, exp02 and exp03 are **stopped** (all below buy-and-hold on the honest validation path). The next family is
  "stay invested, exit rarely" (exp04-exp07 in the roadmap), then VIX, then text.
- Nicolas's instructions in the chat override this file, except the "never" rules of `research-integrity.mdc`, which he
  must change in the file himself.
