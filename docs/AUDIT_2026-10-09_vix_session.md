# Audit of the agent's VIX session (exp08), 2026-10-09

*Independent audit by the assistant of branch `agent/research` of `nicolaser55/stock_overflow_workspace`, commits
`5131de7` → `41f180c` (2026-10-09 12:20 → 13:09 +0300), against the prompt `claude/AGENT_PROMPT_VIX_2026-10-09.md` and
the checklist `claude/AUDIT_CHECKLIST_VIX_2026-10-09.md`. Method: commit order and contents; diffs after
pre-registration; code review of `so/features/vix_features.py`, `so/vix_config.py`, `experiments/exp08_vix_signal_check/
gates.py`; the saved outputs of `step01_vix_gate.ipynb` and `pipeline/step07_VIX_data_check.ipynb`; the trial-log
snapshot; all test suites run on `41f180c` (auditor's sandbox, Python 3.13, the repo's pinned pandas/numpy/LightGBM/
scikit-learn). The notebooks were NOT re-executed: the data folder is only on nicodesktop.*

## Verdict

**The result stands: the VIX line is correctly closed by its pre-registered gates.** Every number in the agent's reply
equals the saved notebook outputs; pre-registration preceded the run; nothing after it changed except status and
change-log lines; the untouched window was not read (last date loaded 2026-05-13, the session before it); no look-ahead
found; 11 of 11 test suites pass; 6 trials against a budget of 10. Two minor record issues (A2, A3) and one
gate-design weakness (A1) are disclosed below; none changes a decision.

## Verified

| # | Check | Evidence | Result |
|---|---|---|---|
| V1 | Branch | `agent/research` created from `a4418d8` (merge-base) | Pass |
| V2 | Order | roadmap `5131de7` 12:20:21 → rename check `b7069ea` 12:24:01 → data layer `bb3e595` 12:38:54 → `preregister exp08` `2c810d1` 12:52:51 → first trial 12:55:00 → results `41f180c` 13:09:38 | Pass |
| V3 | Pre-registration content | `2c810d1` holds protocol, config, `gates.py`, tests and the notebook without outputs; after it only a status line and a change-log line in the protocol (`git diff 2c810d1 41f180c`) | Pass |
| V4 | Roadmap first | `docs/RESEARCH_STATE_2026-10-09.md` with exp08-exp11 committed before any VIX code or data read | Pass |
| V5 | Rename check | `scripts/check_spy_rename.py`, no trial: 5,436 sessions; +69.02% / +50.39%; exp04 x = 0, n = 1 +108.03%, 35 exits; buy-and-hold +235.39% | Pass (agent's output; not re-run) |
| V6 | Loaders | cutoff required, refused on or after 2026-05-14; 1-minute files after the cutoff never opened; daily rows dropped after parsing, then asserted; date = New York date of the timestamp; tested with planted 2026-05-14 rows and a corrupt later file | Pass |
| V7 | Timing / look-ahead | `_prev` = latest daily bar strictly before the session (`searchsorted(..., "left") - 1`); `_intraday` = same-date as-of merge capped at `decision_ts - 1 min` (15:57 full day, 12:57 half day, tested); percentile on the 250 previous values; `chg5` by shift; `fade` max including today; `vrp` from the trailing `daily_volatility`; truncation test passes for both variants and a half day | Pass |
| V8 | Data cut | exp08 notebook: SPY and all four VIX series to 2026-05-13; largest label end 2026-05-13; schedule asserted (44 folds, 2015-03-18, 2015-04-17, 2026-04-15, 2026-05-14) | Pass |
| V9 | G2 purge | `assert max(train label_end_date) < valid_start` for every fold; BASE and AUGMENTED on identical rows (asserted) | Pass |
| V10 | Null | the six VIX columns rolled together by k ∈ [25%, 75%] of 4,193 rows (shifts 1,347-3,118), seeds 20261009 + i; bin edges and models re-learned | Pass |
| V11 | Gate rules | `get_gate_decision_dict`: exp09 = G1 or G2; exp10 = G3 and G4; exp11 = G2; primary only | Pass |
| V12 | Trials | 6 rows, stage `signal_check`, hash `43e86ccb06`, all at 12:55:00, `test_window_touched` False; snapshot 3,299 (+ 4,089 legacy = 7,388) | Pass |
| V13 | Shared code | `so/config.py` unchanged; `so/paths.py` additions only; test helpers added; all earlier suites pass | Pass |
| V14 | step07 (run before pre-registration) | uses no label, return or close column (searched); data quality only | Pass (no contamination of the gate) |
| V15 | Deviations | validation rows = the 44 replay periods (each session once), and analysis start 2009-08-13 (term feature needs a previous VIX3M close): both in the pre-registered protocol (§3, §11), conservative | Pass |

## Results (copied from the saved outputs of `step01_vix_gate.ipynb`)

| Gate | Real | Null / interval | Result |
|---|---|---|---|
| G1 signal bins (6 features × 5 bins, 30 tested) | S1 = 0 | 19 runs all 0; p = 1.00 | FAIL |
| G2 dAUC, 2,765 pooled predictions | AUC BASE 0.4233 [0.3648, 0.4829], AUGMENTED 0.4592 [0.3995, 0.5174], dAUC +0.0359 [−0.0025, +0.0709] | null +0.0043 … +0.0563, 2 runs ≥ real; p = 0.15 | FAIL |
| G3 volatility forecast | Spearman VIX 0.6357 vs trailing 0.5193, D +0.1165 [+0.0441, +0.2227] | 6-month blocks | PASS |
| G4 top VIX quintile (≥ 22.94) mean 20-session net return | training +1.91% [+0.89, +2.94]; validation +2.82% [+1.60, +3.90] | needs both < 0 | FAIL |
| G1 / G2 intraday (secondary) | S1 = 0; dAUC +0.0291 | null max 0 / +0.0628; p 1.00 / 0.25 | would not pass |

Decisions: exp09, exp10, exp11 not run. Descriptive: mean forward 20-session return by VIX quintile, validation +0.49%,
+0.47%, +0.80%, +0.51%, +2.82%; inverted term structure +3.07% (220 rows) vs +0.81%.

**Mathematically.** G2 compares two ranking scores: AUC = P(p̂_i > p̂_j | y_i = 1, y_j = 0). Under H0 "the VIX columns
carry no information beyond the price features", rolling them against the labels gives exchangeable copies of dAUC
that keep the model's flexibility; the real +0.0359 ranks 3rd of 20 (p = 0.15). G4 tests the necessary condition for
unlevered scaling: the excess over buy-and-hold is −Σ (1 − w_t) r_t − costs, which is positive only if the sessions with
w_t < 1 have r_t < 0 on balance; E[r | top VIX quintile] is +2.82% per 20 sessions, about three times the unconditional
mean (≈ +0.99%, weighted from the term-structure table), so the condition fails in both windows.

**In plain words.** The VIX says how rough the next month will be, not which way SPY goes; and after high-fear days
SPY did better than usual, so any rule that holds less SPY when fear is high gives up the best months.

## Issues

| # | Severity | Issue | Action |
|---|---|---|---|
| A1 | Moderate (design, disclosure) | **The gate of exp09 did not test exp09's mechanism.** exp09 bets that buying back when fear fades beats the price rules; that is a claim about the *size* of returns after high fear. Its gates were G1 (share of positive 20-session returns per bin) and G2 (ranking of the sign). The descriptive table shows the effect lives in the mean (top quintile +2.82% vs ≈ +0.99%; inverted term structure +3.07% vs +0.81%), while the positive *share* moves little (0.74 vs 0.67, interval includes the base rate). The 2026-10-08 design had this gate; the assistant's 2026-10-09 revision kept it and did not see the mismatch. G1 also had little power: training is 1,408 overlapping sessions (67 months) and every null run gave S1 = 0. The STOP stands as pre-registered; reopening exp09 now would be a **data-dependent** version motivated by these descriptive numbers | Record in the thesis limitations: "the exp09 gate tested the sign, not the magnitude, of forward returns; the descriptive pattern after high VIX (higher mean returns) was not tested" |
| A2 | Minor (wording) | The results log's "Mathematically" paragraph states as fact that the null gains arise "because with the same regularization the extra columns dilute the BASE model's (wrong-signed) weights". The agent's chat reply correctly calls this an inference; it was not tested | Add a dated correction: "consistent with … (an inference, not tested)" |
| A3 | Minor (record) | The six exp08 trial-log rows leave `train_start`, `train_end`, `valid_start`, `valid_end`, `test_start`, `test_end` empty (the windows are only in `setting_json` as `analysis_start` and `data_cutoff`); exp02's signal-check row filled them | None needed for the result; mention if the trial log is used in the thesis |
| A4 | Informational (finding) | **BASE AUC 0.4233 with its whole interval below 0.5**: the 16 price features, trained on 2009-2015 onwards, rank the next 20 sessions in the wrong order out of sample. Third observation of this reversal (exp02 mean validation AUC 0.470; exp01 step 04 large distances 0.41-0.44). It is not a tradable result (inverting it would be chosen after the fact); it is evidence of non-stationarity | Report in the cross-experiment notes |
| A5 | Informational | `AGENTS.md` still says "Next: the VIX line"; `records/bad_tick_corrections.csv` keeps the old folder name in `backup_path` (a historical record, correctly left) | Nicolas updates `AGENTS.md` when merging |
| A6 | Informational (data) | Daily vs last 1-minute close disagree on 2.6% (VIX) and 10.6% (VIX3M) of dates, a few by much (VIX 2026-01-16 18.84 vs 15.86). Unexplained; the primary timing uses the daily close. Not compared with Cboe | Keep in the data limitations |

## Trials and data use

exp08 6 trials; workspace 3,299; with legacy 7,388. 2015-2026 reused for the eighth time; 2009-2015 used as the gate's
training span. Untouched window 2026-05-14 → 2026-08-13 not read. No candidate result pending review.
