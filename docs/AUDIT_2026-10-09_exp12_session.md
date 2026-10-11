# Audit of the agent's exp12 session (VIX fear re-entry), 2026-10-09

*Independent audit by the assistant of branch `agent/research`, commits `6bfd642` → `12db4b7` (2026-10-09 14:15 → 14:53
+0300), against `claude/AGENT_PROMPT_EXP12_2026-10-09.md` and its checklist. Method: commit order and contents; diffs
after pre-registration; code review of `experiments/exp12_vix_fear_reentry/rules.py` and the change to
`so/core/reentry_simulation.py`; the saved outputs of both exp12 notebooks; the trial-log snapshot; all 12 test suites
run on `12db4b7` (auditor's sandbox). Notebooks not re-executed (the data folder is only on nicodesktop).*

## Verdict

**The result stands: exp12 fails its primary criterion and the VIX line is closed as pre-registered.** Every number in
the agent's reply equals the saved outputs (one wording point, B1). No integrity problem found.

## Verified

| # | Check | Evidence | Result |
|---|---|---|---|
| V1 | Order | roadmap `6bfd642` 14:15:21 → audit corrections `ca86bd0` 14:15:58 → `preregister exp12` `1e6a2e6` 14:30:48 → first trial 14:31:19 → runs `4b36c65` 14:47:20 → record `12db4b7` 14:53:05 | Pass |
| V2 | After pre-registration | only a change-log line in the protocol; config, rules, simulator unchanged (`git diff 1e6a2e6 12db4b7`) | Pass |
| V3 | Rules | `rules.py` M1 (maximum from the exit decision, NaN skipped), M2 (term ≥ 1 since the exit, NaN false), M3; equal to the quoted exp09 text | Pass |
| V4 | Simulator change | `require_fresh_exit` key, default off; pending flag cleared only on a decision where the exit signal is off; set only if the signal is on at a VIX re-entry; all earlier suites pass and the reproduction asserts hold | Pass (backward-compatible) |
| V5 | Tie-break | `TIE_ORDER_DICT` (E2M3, E2M1, E2M2, E1M3, E1M1, E1M2) in the pre-registered config | Pass |
| V6 | Reproduction asserts | E1 +108.03% / 35 exits; E2 +115.60% / 12 exits; buy-and-hold +235.39% / +229.74% | Pass |
| V7 | Data cuts | step 01: SPY, VIX, VIX3M to 2015-03-18; step 02: to 2026-04-15; no missing VIX values on the replay span | Pass |
| V8 | Trials | 6 exploration + 264 validation + 1 summary = 271 (budget 300); `test_window_touched` False; workspace 3,570, with legacy 7,659 | Pass |
| V9 | Disclosure | results-log entry opens with the data-dependence, gate override, hindsight and ninth-reuse disclosure | Pass |
| V10 | Tests | 12 of 12 suites pass on `12db4b7` | Pass |

## Results (saved outputs of `step02_continuous_replay.ipynb`)

| Path | Total return 2015-2026 | Note |
|---|---|---|
| Buy-and-hold | +235.39% full span; +229.74% prior-only span | |
| E1M1 (best after the fact, optimistic) | **+314.80%** | log excess +1.92%/yr [−1.13%, +6.03%]; 94.0% in market; 35 exits |
| E2M1 | +235.60% | ties buy-and-hold |
| E1M2 / E2M3 / E2M2 / E1M3 | +195.83% / +168.95% / +167.51% / +132.68% | |
| **Prior-only path (honest)** | **+119.24%** vs +229.74% | log excess −3.77%/yr [−7.95%, −0.37%] (6-month blocks; 1-month [−7.80%, +0.30%]); 29 exits; 89.5% in market; 7 of 43 periods won |
| Unmodified prior-only {E1, E2} | +82.88% | exp12 beats it |
| Random exits, same re-entry (median of 20) | +187.43% | path beats 0 of 20 |
| Random re-entries, same exits (median) | +90.60% | path beats 13 of 20 |

Concentration: Π S/R 0.6661 over 29 episodes (equity ratio 0.6649); 0.6269 without the best episode, 0.5926 without the
two best; negative log excess in every year but 2025 (+0.0237); 2023 −0.1855; 2020 episodes 8% of the total −0.4081.
Selections: E1M1 governed 20 of 44 periods, E2M1 7, E2M2 7, E2M3 5, E1M2 2, E1M3 2.

**Mathematically.** Final equity ÷ buy-and-hold = Π S/R (0.666), i.e. Σ log(S/R) ≈ −0.406. By the agent's post-hoc split
of the saved scorecard (not printed by the notebook, not verified here): the VIX-triggered buy-backs multiply to
1.1324 (M1, 4 episodes) and 1.0538 (M2, 6), the 19 buy-backs by the original price rules to 0.5582. The VIX
re-entries did buy back below the sale price on balance; the price-rule exits that the VIX never rescued lost more. The
information test explains where: random exits with the same re-entry rule earn +187% and beat the path every time, so
the trend and lights **exits** are worse than random (as in exp04 and exp07), whatever the re-entry.

**Why after the fact and prior-only differ by 195 points.** The prior-only path must choose each quarter's candidate
from the previous four quarters. Examples from the scorecard and the selections:
- Q1 2020 was governed by E1M2 (selected at fold 18 with the best of six *negative* pooled scores, −0.0088). M2 waits
  for the term structure to return below 1, so the exit of 2020-03-05 (302.65) was bought back only on 2020-04-17
  (286.55), when the period governed by E1M1 began and its fade condition was already true. *Inferred, not verified
  from the repo:* E1M1 alone would have bought back in late March 2020, near the low, if the IBKR daily closes match
  the public VIX (82.69 on 2020-03-16, 66.04 on 2020-03-20).
- Late 2022 and 2023 were governed by E1M3 and E2M2, whose buy-backs are the original price rules: 2022-09-29 →
  2022-11-30 (S/R 0.8925, the worst episode) and the 2023 exits (log excess −0.1855 for the year).
- Many pooled scores were exactly 0 (all candidates invested), so the pre-registered tie order decided several
  periods.

This is the clearest illustration in the project of why the prior-only path is the estimate: the best of six candidates
beat buy-and-hold by 79 points with hindsight; a procedure using only past data lost 110 points with the same six.

## Issues

| # | Severity | Issue | Action |
|---|---|---|---|
| B1 | Minor (wording) | The agent's reply says the log-excess interval "lies entirely below 0": true for the primary 6-month blocks [−7.95%, −0.37%]; the 1-month version [−7.80%, +0.30%] includes 0 | State both in the write-up |
| B2 | Informational | E1M1's after-the-fact +314.80% is one of six, rules written with hindsight of the 2020 crash, interval includes 0; it is not evidence and cannot be adopted now (that would be choosing after seeing results) | Report it labelled optimistic, next to the prior-only path |
| B3 | Informational | Ties at a pooled score of 0 were broken by the pre-registered order in several periods; the prior-only path partly reflects that arbitrary order. A re-run with another order would be a choice made after seeing results | Disclose; no re-run |
| B4 | Informational | The M1 / M2 / original-rule split of Π S/R is the agent's post-hoc calculation from the saved scorecard | Label as descriptive |
| B5 | Assistant's own error | Before the run the assistant said the prior-only path had "real odds" of beating buy-and-hold, mostly through 2020; it did not (the after-the-fact best did) | Recorded |
| B6 | Process | `AGENTS.md` on main (`22ad606`) still says "Next: the VIX line" | Nicolas updates it when merging |

## State after exp12

All pre-registered lines are closed: exp01-exp08 and exp12 stopped, exp09-exp11 skipped by exp08's gates. 3,570
workspace trials, 7,659 with legacy. Untouched window 2026-05-14 → 2026-08-13 never read. Parked for Nicolas: the
write-up of the negative result (the agent offers to draft it), text data.
