# Audit of the agent's exp13 session (E1M1 robustness), 2026-10-09

*Independent audit by the assistant of branch `agent/research`, commits `ce2df27` → `05ac8c3` (2026-10-09 19:38 → 20:37
+0300), against `claude/AGENT_PROMPT_EXP13_2026-10-09.md` and its checklist. Method: commit order and contents; diffs
after pre-registration; review of `experiments/exp13_e1m1_robustness/robustness.py`; the saved outputs of the four
notebooks; the trial-log snapshot; all 13 test suites run on `05ac8c3`. Notebooks not re-executed (data only on
nicodesktop).*

## Verdict

**The result stands: E1M1 IS NOT ROBUST (R1-R4 fail, R5 holds).** Every number in the agent's reply that I checked
equals the saved outputs. One design flaw in the placebo set (C1) is the assistant's, from the prompt; it does not
affect the verdict, which rests on R1, R2, R3 (P2) and R4.

## Verified

| # | Check | Evidence | Result |
|---|---|---|---|
| V1 | Order | roadmap and override `ce2df27` 19:38:34 → exp12 notes `cc243d6` 19:38:45 → `preregister exp13` `afe6b42` 19:57:17 → first trial 19:57:49 → steps 01-04 (19:58 → 20:33) → record 20:37 | Pass |
| V2 | After pre-registration | only the protocol's change-log lines; config, `robustness.py`, shared code and tests unchanged | Pass |
| V3 | Interrupted session | the agent's reply says Part 0, the pre-registration and step 01 were already committed when it resumed; trial rows have no duplicate settings and each stage has exactly the planned count | Pass (no re-run) |
| V4 | Reproduction | DEV E1M1 +314.80% / 35, E1 +108.03% / 35, B&H +235.39%; exp12 step 01 E1M1 +104.51%, E1 +49.00%, B&H +104.57% | Pass |
| V5 | Data cuts | STRESS notebooks to 2015-03-18; DEV to 2026-04-15; STRESS starts 2005-10-18 (first session with the 200-session average and a VIX close) | Pass |
| V6 | Trials | 2 exploration + 74 robustness + 4 placebo + 1 summary = 81 (budget 150); `test_window_touched` False; workspace 3,651, with legacy 7,740 | Pass |
| V7 | Neighbourhood | the variant code at 0.85 / 200 / fresh-on equals the frozen rule; MA length changes both exit and original re-entry; nothing selected | Pass |
| V8 | Placebos P1/P2 | the whole VIX feature block rolled by k ∈ [25%, 75%] of the rows, seeds NULL_SEED + run; P2 replays all six exp12 candidates per run and takes the maximum; p = (1 + k)/1000 | Pass |
| V9 | Verdict | R1-R5 computed and applied as pre-registered | Pass |
| V10 | Rules files | `.cursor/rules/` unchanged; `AGENTS.md` changed only in the status bullet (accurate) | Pass (see C2) |
| V11 | Tests | 13 of 13 suites pass | Pass |

## Results (saved outputs)

| Criterion | Number | Result |
|---|---|---|
| R1 STRESS 2005-10-18 → 2014-12-31 | E1M1 +53.32% vs B&H +73.09% (2007-10 → 2009-08: −34.57% vs −34.16%; E1 alone −5.65%) | FAIL |
| R2 PLATEAU | 11/36 beat B&H on DEV (need 24), 3/36 on STRESS (need 18); 2/36 on both; E1M1 rank 1 of 36 on DEV | FAIL |
| R3 selection-aware placebo P2 | p = 0.088 (null median +254.35%, 95th +331.64%) | FAIL |
| R4 without the best episode (2020-03-05 → 03-16, S/R 1.2652) | equity / B&H 0.9775 (two best removed: 0.8945) | FAIL |
| R5 execution | one session late +306.15%; 5 cents +310.85% | PASS |

Other: P1 p = 0.088 (null median +251.56%); P3 p = 0.001; P4 p = 0.013. 2020 episodes carry 69% of the log excess
(+0.2125); halves +3.53%/yr (2015-2020) and +0.20%/yr (2021-2026). Π S/R by reason: M1 1.8188 (13 episodes), original
rule 0.6808 (22).

**Mathematically.** Final equity ÷ buy-and-hold = Π S/R. E1M1's 1.237 on DEV (4.1480 / 3.3539) is 1.2652 (one 2020
episode) × 1.0928 (one 2018 episode) × 0.895 for the other 33 episodes together. The misaligned-VIX null (P1) has a median of +251.56%, above
buy-and-hold: most of E1M1's advantage over buy-and-hold on DEV comes from its **structure** (sell below the average,
buy back quickly, then ignore the sell signal until it resets: 94% invested), not from the VIX's timing. The aligned
VIX adds +314.80 − 251.56 ≈ 63 points over the null median, ranking 88th of 1,000 (p = 0.088). The grid shows the same
thing: every fresh-signal-off variant loses 84-163 points on DEV, while the fresh-on variants mostly sit near or above
buy-and-hold. On STRESS the same structure is what failed: the M1 buy-back of 2008-02-01 ignored every later sell signal
while SPY fell to 68.07 (−51% from the buy-back).

**In plain words.** "Sell when SPY drops below its 200-day average, buy back as soon as fear starts to ease, then sit
tight" did well in 2015-2026 because nearly every decline was a fast V. It lost in 2008, a slow decline, and its
2015-2026 edge is mostly one week in March 2020. Misaligned VIX data does almost as well, so the VIX itself is not what
made it work.

## Issues

| # | Severity | Issue | Action |
|---|---|---|---|
| C1 | Moderate (design; assistant's prompt) | **P3 is not a like-for-like placebo.** `get_random_reentry_func` sets no `require_fresh_exit`, so after a random buy-back while SPY is still below its average the random path sells again at the next decision; E1M1 keeps the position. P3's p = 0.001 measures the fresh-signal structure plus timing, not VIX timing. P1/P2 keep the structure and are the clean tests (p = 0.088). The prompt asked for "exp04's random re-entry family" without this caveat | Dated note in exp13's results-log entry: "P3 compares E1M1 with random re-entries that lack the fresh-signal rule; it is not evidence of VIX timing" |
| C2 | Minor (process) | The agent edited `AGENTS.md` (Nicolas's operator file) itself; the content is accurate and only the status bullet changed | Nicolas accepts or rewrites it when merging |
| C3 | Minor (record) | Window columns: `test_start` empty on all exp13 rows (valid columns filled) | None |
| C4 | Informational | P1 and P2 have the same rank (88) and 95th percentile: in every shifted run where any of the six candidates reached +314.80%, E1M1 did too | None |
| C5 | Informational | joblib printed a non-fatal resource_tracker KeyError after the 999-run parallel step; outputs and trials complete | None |

## State after exp13

Every line pre-registered or decided by Nicolas is closed: exp01-exp08, exp12 and exp13 stopped; exp09-exp11 skipped.
3,651 workspace trials, 7,740 with legacy. The untouched window 2026-05-14 → 2026-08-13 has never been read. Parked:
the write-up of the negative result (deferred by Nicolas until after exp13, so now due), text data.
