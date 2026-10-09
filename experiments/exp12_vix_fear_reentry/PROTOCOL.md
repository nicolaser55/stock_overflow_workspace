# exp12_vix_fear_reentry: Protocol (a data-dependent follow-up of exp08)

*Version 1.0 (2026-10-09). Experiment name `exp12_vix_fear_reentry`. Config: `experiments/exp12_vix_fear_reentry/config.py`
+ `so/config.py` (the VIX constants of `so/vix_config.py` and the exit settings of exp04 / exp07 used here are assigned
to the experiment config, so the hash covers them). Decided by Nicolas on 2026-10-09 (answer (b) to the parked decision
"VIX line closed"); written by the agent in autonomous mode and committed (message `preregister exp12`) before any run of
this experiment. After the first validation run, at most one new version, only to fix a defect (never a rule change),
labelled with its reason. This is the LAST VIX re-entry test: no later version may be motivated by its results.*

---

## 1. Why this exists (data-dependence and hindsight disclosure)

- exp08's pre-registered gates did not open exp09 (G1 S1 = 0, p = 1.00; G2 dAUC +0.0359, null max +0.0563, p = 0.15).
- After seeing exp08's descriptive table (mean 20-session forward return after a top-quintile VIX +2.82% vs about +1%
  on validation; after an inverted term structure +3.07% vs +0.81%), Nicolas decided on 2026-10-09 to run the VIX-timed
  re-entry anyway. **The decision to run is therefore DATA-DEPENDENT, and it overrides a pre-registered gate.**
- The independent audit of 2026-10-09 (issue A1) noted that exp09's gates tested the SIGN of forward returns (G1, G2),
  while exp09's mechanism concerns their SIZE after fear peaks.
- The **RULES are NOT data-dependent on exp08**: they are exp09's rules exactly as Nicolas sent them on 2026-10-09
  before exp08 ran (summary in roadmap commit `5131de7`, 12:20:21; exp08's first trial 12:55:00). They are quoted
  verbatim in §4. Nothing is changed, added or tuned.
- **Hindsight:** these rules were written by people who know the 2018, 2020, 2022 and 2025 declines and their VIX peaks.
- 2015-2026 is development data, **reused here for the ninth time**.
- This is the **LAST** VIX re-entry test: no later version may be motivated by its results.

## 2. Question and hypothesis

*Question:* do VIX-timed re-entries (or a VIX filter on exits) turn exp04's trend exit (E1) or exp07's lights (E2)
into a path that beats buy-and-hold's total return on the honest prior-only path of 2015-2026?

*Hypothesis (exp09, 2026-10-09):* exp04 and exp07 lost because they sold late and bought back after the rebound (every
buy-back above the sale price); VIX peaks and the return of the term structure to contango mark rebounds earlier than
price rules.

*The identity that decides success:* an episode that sells at S and buys back at R ends with S / R times the shares;
final equity / buy-and-hold ≈ Π S / R over the episodes (costs and integer-share cash residues aside). exp04's prior-only
product was well below 1 (12 exits, all bought back higher); the VIX rules can only help by moving R below S.

## 3. Data

- **SPY:** IBKR 1-minute bars (`store01_rawzone/ibkr_spy_1min/`), daily table from `so.features.daily_features`
  (decision bar = second-to-last bar of each session; fill = open of the last bar).
- **VIX / VIX3M:** IBKR daily bars of `store01_rawzone/ibkr_vix_family/` (approved by Nicolas on 2026-10-08), read only
  through `so.features.vix_features.get_vix_daily_feature_dict` with variant `"prev"` only: every feature of session t
  uses the daily closes dated strictly before t (the previous session's close; NaN if more than 3 SPY sessions stale;
  VIX3M NaN before 2009-08-12). The loader cutoff always equals the SPY cut of the notebook; it refuses 2026-05-14 and
  later. **The `_intraday` secondary variant of exp09 is dropped** (Nicolas, 2026-10-09, before any exp12 run: it could
  never decide a verdict, exp08 showed it adds nothing, and dropping it halves the trials).
- **Exploration (step 01, context only, stage `exploration`):** SPY and VIX cut at `so.config.EXPLORATION_DATA_CUTOFF_DATE_STR`
  (2015-03-18); each of the 6 candidates runs as one continuous path over 2009-08-13 → 2014-12-31 (the term feature
  exists from 2009-08-13), against buy-and-hold and the unmodified E1 and E2 over the same span: 6 entries.
- **Validation (step 02):** the 44-period schedule built exactly as exp04 step 02 (from the full session calendar, dates
  only), asserted: 44 periods, first valid_start 2015-04-17, last valid_end 2026-04-15, latest test_start 2026-05-14
  (never read). SPY bars cut at 2026-04-15 before any computation, VIX loader cutoff 2026-04-15. The notebook prints the
  last SPY and VIX dates loaded.

## 4. Rules (quoted verbatim from the 2026-10-09 prompt, exp09; every word applies to exp12)

> Exits, FIXED from earlier experiments and not re-tuned, each with its original re-entry rule as the fallback:
>    - E1 = exp04's textbook trend rule (x = 0, n = 1): exit when the decision close is below the 200-session average,
>      re-enter when above (exp04's rules.py).
>    - E2 = exp07's lights (k = 4): exit when at least 4 lights are on, re-enter when fewer than 3 are on (exp07's
>      rules.py).
>
> Modifications (parameters fixed, no grid):
>    - M1 fear-fade re-entry: buy back at the first decision after the exit where vix_level_prev <= 0.85 x max(vix_level_prev
>      over the decisions from the exit decision to now), or when the original re-entry fires, whichever comes first.
>    - M2 term-structure re-entry: buy back at the first decision where vix_term_prev < 1, provided vix_term_prev was >= 1
>      at least once from the exit decision on; or when the original re-entry fires, whichever comes first. NaN = condition
>      false.
>    - M3 no exit into fear: the exit signal is ignored at decisions where vix_term_prev >= 1 or vix_pct250_prev >= 0.9
>      (NaN = not suppressed); original re-entry.
>    - For M1 and M2: after a VIX-triggered re-entry, a new exit requires the exit signal to switch off and on again (a
>      fresh signal); otherwise the rule would sell again the next session. Implement this in the experiment's code (or
>      as a backward-compatible, tested addition to the shared simulator) and test it.
>
> Clarifications (they add no freedom): in M1, a NaN vix_level_prev makes the condition false and does not enter the
> maximum; the fresh-signal rule applies only after a VIX-triggered re-entry, never after the original rule's re-entry.

**Candidates:** E1M1, E1M2, E1M3, E2M1, E2M2, E2M3 = 6 candidates, `_prev` features only. No forced buy-back
(`MAX_CASH_SESSIONS = None`), no stop; trades fill at the open of the last bar of the decision session (± $0.01
slippage), IBKR fees, cash earns 0%.

**Implementation (`rules.py`):**
- E1: `experiments/exp04_trend_exit/rules.get_trend_exit_signal_arr(daily, 0.0, 1)` and `get_trend_reentry_signal_arr(daily, 0.0)`.
- E2: `experiments/exp07_warning_lights_exit/rules.get_light_pdf` with exp07's `LIGHT_DICT`: exit at ≥ 4 lights, original
  re-entry at < 3.
- The **exit decision** of an episode is the session of the sale (the session before its first cash decision). M1's
  maximum and M2's "was ≥ 1" condition are read from the feature arrays over the sessions exit decision … now
  (`get_m1_trigger_bool`, `get_m2_trigger_bool`), so they do not depend on which candidate governed earlier sessions of
  the episode on the prior-only switching path.
- M3: exit signal AND NOT (`vix_term_prev` ≥ 1 OR `vix_pct250_prev` ≥ 0.9), a NaN comparison being false (`get_m3_suppress_arr`).
- When the original rule and a VIX trigger fire on the same decision, the re-entry is labelled **original** (so the
  fresh-signal rule does not apply). For both exits the original re-entry implies the exit signal is off at that decision
  (above the average for E1; fewer than 3 lights, hence not ≥ 4, for E2), so the label changes no trade.
- **Fresh signal:** a backward-compatible addition to the shared simulator `so.core.reentry_simulation.simulate_stop_reentry_dict`
  (§11): a re-entry rule may set `episode_dict["require_fresh_exit"] = True`; if the exit signal is on at the re-entry
  decision, the simulator then ignores it until it has been off on at least one decision. Without the key (every rule
  of exp01-exp07) the behaviour is unchanged.

## 5. Walk-forward and selection

- **Candidate paths (after the fact):** `so.core.replay_walk_forward.run_candidate_replay_dict` replays each candidate
  continuously over the 44 periods; each (candidate, period) is one validation trial, logged with the fold columns
  filled (the fold schedule is passed as in exp04): 6 × 44 = 264 entries.
- **Selection:** exp04's pooled rule (`run_prior_only_replay_dict`): mean period excess over the last 4 periods;
  the candidate selected at period f governs period f + 1 (one continuous switching path from period 2, 2015-07-17).
- **Tie-break (fixed before any run):** rank E2M3, E2M1, E2M2, E1M3, E1M1, E1M2 (`config.TIE_ORDER_DICT`). E2 before E1
  and M3 first follow the convention of exp04 / exp07 (fewest exits = closest to buy-and-hold: on 2015-2026 E2 made 12
  exits and E1 35; M3 only removes exits); M1 before M2 is arbitrary. With rare exits many periods tie (or nearly tie),
  so this order governs many periods; it is reported.
- One summary entry. Expected total 6 + 264 + 1 = **271 trials (budget 300)**.

## 6. Baselines (computed, not logged as trials)

- Buy-and-hold over the same sessions.
- **The UNMODIFIED exits:** the prior-only path over {E1, E2} with the same selection (ties: E2 first), and E1 and E2
  alone over the 44 periods — the direct test of what the VIX adds.
- **Random re-entries after the same exits, and random exits with the same re-entry rule** (20 runs each; exp04's seeds
  convention and functions: random exit run i uses `RANDOM_SEED + 1000 + i`, random re-entry run i `RANDOM_SEED + i`;
  probabilities matched to the path's exit frequency and mean time in cash).

**Reproduction asserts (step 02, before any exp12 number is printed):** unmodified E1 alone over 2015-04-17 → 2026-04-15
= +108.03% with 35 exits; unmodified E2 alone = +115.60% with 12 exits; buy-and-hold = +235.39% (full span) and +229.74%
(prior-only span from 2015-07-17). Percent to 2 decimals, exact exit counts. If any differs: stop, record it, park it.

## 7. Reporting (as exp04-exp07)

The optimistic best candidate after the fact (labelled optimistic); the prior-only path vs buy-and-hold; annualized
log excess with the 6-month-block interval (1-month alongside); periods won with a sign test; MDE; time in the market;
Sharpe; maximum drawdown; cost sensitivity (0 / 1 / 2 cents); the selections per period; the episode scorecard with,
for every episode, exit date and fill S, buy-back date and fill R, S/R, sessions out, re-entry reason (M1, M2, original
rule, or end of data), and `vix_level_prev` at the exit and at the buy-back.

**Pre-registered concentration reports (no gate; always printed):**
- (a) final equity / buy-and-hold = product of S/R; also without the single episode with the largest log(S/R), and
  without the two largest (the equity ratio divided by their S/R); whether the path still beats buy-and-hold without them.
- (b) the log excess over buy-and-hold per calendar year, 2015-2026 (2015 from 2015-07-17, 2026 to 2026-04-15).
- (c) the share of the total log excess log(final equity / buy-and-hold) contributed by the episodes that overlap
  2020-02-01 → 2020-06-30 (sum of their log(S/R) / total).

## 8. Success and stopping (pre-registered exactly)

- **Primary:** the prior-only path beats buy-and-hold's total return (+229.74% on 2015-07-17 → 2026-04-15).
- **Information test:** the prior-only path also beats the unmodified prior-only path AND the median of both random
  families.
- **If the primary fails: STOP.** The VIX line closes definitively; no further version.
- **If the primary passes, it is NOT a success claim** (research-integrity "Never 5"). Record "candidate result pending
  review" (with "information test failed: not attributable to the VIX" if the information test fails) with: the
  concentration reports; the biases (dividends ignored, cash at 0%, informal costs); every limitation of §1; the trial
  count (3,299 workspace + 4,089 legacy + exp12's). Then park for Nicolas: "exp12 candidate: forward test or untouched
  window", noting that the untouched window (2026-05-14 → 2026-08-13, 63 sessions) is very unlikely to contain a full
  exit and buy-back episode, so it cannot confirm a re-entry rule; only forward data can.
- At most one new version, only to fix a defect (never a rule change), labelled with its reason.

## 9. Trial budget

6 exploration + 264 validation + 1 summary = **271**, **budget 300**. Each notebook asserts the budget before it logs.
A notebook is run once; a crash half-way is recorded with the trials it logged, and the notebook is re-run once.

## 10. Known limitations and biases

- Everything in §1: the decision to run is data-dependent and overrides exp08's gate; the rules carry hindsight of the
  2018, 2020, 2022 and 2025 declines; 2015-2026 is reused development data (ninth use); this is the last VIX re-entry test.
- The trial count the conclusion rests on: 3,299 workspace trials before exp12 plus the 4,089 legacy trials, plus exp12's.
- Few events: E1 and E2 exit 12 to 35 times on 2015-2026; the result rests on a handful of episodes (hence the
  concentration reports).
- VIX3M starts 2009-08-12 in the IBKR data (the exploration starts 2009-08-13); the IBKR index data was not compared
  with Cboe's official values (the daily close and the last 1-minute close disagree on 2.6% of VIX and 10.6% of VIX3M
  dates, `docs/RESULTS_LOG.md`, VIX data layer). The `_prev` timing uses the previous session's daily close only, so the
  unproven 1-minute bar-label convention does not enter this experiment.
- Simulator biases (`docs/RESEARCH_STATE_2026-10-09.md` §4): dividends ignored (favours time in cash), cash at 0%
  (penalizes it), informal costs (slippage $0.01/share per side, IBKR fixed fees; no gap model beyond the fill at the open
  of the last bar).
- The tie-break order (§5) governs every tied period; its E2-first / M3-first part follows the family convention, the
  M1-before-M2 part is arbitrary.

## 11. Methodological choices (the most conservative option)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| Fresh-signal rule | (a) block exits for the c sessions until the signal turns off, computed at the re-entry from the exit array; (b) a state flag in the shared simulator, cleared when the signal is off | (b), backward-compatible, tested | (a) would read the future of the exit array (same trades, but not causal in code) and breaks on the switching path when the governing candidate changes inside the block; (b) is causal and uses the exit signal actually in force |
| Exit decision of an episode | the sale session / the first cash session | the sale session | "from the exit decision to now" includes the exit decision's own VIX value (higher maximum: the stricter M1) |
| Same-decision tie of original and VIX trigger | label VIX / label original | original | The fresh-signal rule then never applies where the VIX was not needed (no trade differs for E1 / E2, see §4) |
| Tie-break of the selection | candidate order / fewest exits first | fixed rank E2M3 … E1M2 (§5) | Closest to buy-and-hold first, the convention of exp04 / exp07; fixed before any run |
| Verdict when the primary passes but the information test fails | STOP / candidate | candidate, labelled "information test failed: not attributable to the VIX" | The roadmap's stopping rule is the primary only; the label prevents the result from being read as VIX information |
| Unmodified baseline path | E1 alone / E2 alone / prior-only over {E1, E2} | all three; the information test uses the prior-only path | Same selection as the exp12 path: the only difference is the VIX modification |

## 12. Implementation

| File | Content |
|---|---|
| `config.py` | Every constant (exits, modifications, VIX columns, tie order, schedule, reproduction targets, baselines, concentration window, exploration window, budget) |
| `rules.py` | Schedule, candidates, base signals, M1 / M2 / M3, rule builder, re-entry reasons, VIX scorecard, concentration and yearly reports |
| `step01_exploration.ipynb` | 2009-08-13 → 2014-12-31 continuous paths of the 6 candidates and the unmodified exits (6 trials) |
| `step02_continuous_replay.ipynb` | Reproduction asserts, unmodified baseline path, 6 candidate paths (264 trials), prior-only path with baselines, scorecard, concentration reports (1 summary) |
| `tests/test_exp12.py` | Candidates, base signals = exp04 / exp07, M1-M3 by hand (NaN rules), fresh-exit option of the simulator, mechanics, no look-ahead, walk-forward and tie-break, reports |
| `so/core/reentry_simulation.py` | Backward-compatible `require_fresh_exit` option (absent = unchanged behaviour) |

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-09 | Initial protocol (agent, autonomous mode, from Nicolas's decision of 2026-10-09), pre-registered before any run (`1e6a2e6`) |
| 1.0 (result) | 2026-10-09 | Run once (271 trials, as expected). Primary fails (prior-only +119.24% vs +229.74%) → **STOP** by §8; the VIX line is closed definitively. No new version (no defect found). Details: `docs/RESULTS_LOG.md`, exp12 |
