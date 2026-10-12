# exp12_vix_fear_reentry_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp12_vix_fear_reentry_v2`. Config: `experiments/exp12_vix_fear_reentry/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** Data-dependent follow-up of exp08, as protocol 1.0. Nothing was tuned and no rule was added. This remains the last VIX re-entry test: no further version may follow from this result.

Protocol 1.0's result is in `docs/RESULTS_LOG.md` (prior-only +119.24% vs buy-and-hold +229.74%, STOP; 271 trials). Its code and notebooks are at tag `pre-port-20261012`.

## 1. Question and rules (protocol 1.0, unchanged)

Do the six VIX modifications turn E1 or E2 into a path that beats buy-and-hold's total return on the prior-only path?

Exits, fixed, each with its original re-entry as the fallback:

- E1 = exp04's textbook trend rule (x = 0, n = 1).
- E2 = exp07's lights (k = 4): exit at 4 or more lights, buy back below 3.

Modifications, parameters fixed:

- M1: buy back when `vix_level_prev` ≤ 0.85 × its maximum from the exit decision through now, or when the original re-entry fires, whichever is first. A missing level is false and does not enter the maximum.
- M2: buy back when `vix_term_prev` < 1 after it was ≥ 1 at least once since the exit decision, or when the original re-entry fires. A missing value is neither.
- M3: ignore the exit when `vix_term_prev` ≥ 1 or `vix_pct250_prev` ≥ 0.9. A missing value does not suppress. Original re-entry.
- After a VIX-triggered re-entry of M1 or M2, a new exit waits until the exit signal has been off once (`require_fresh_exit`). Not after the original re-entry. When both fire on the same decision, the reason is "original".

Candidates: E1M1, E1M2, E1M3, E2M1, E2M2, E2M3. Timing is `_prev` only. No stop, no forced buy-back. Fill at the 15:59 open, $0.01/share slippage, IBKR fees, cash at 0%.

## 2. Selection, baselines, success and stopping (protocol 1.0)

Selection: mean excess over the last 4 periods. Ties: E2M3, E2M1, E2M2, E1M3, E1M1, E1M2. The choice at period f governs period f + 1.

Baselines, computed and not logged as trials: buy-and-hold; the unmodified prior-only path over {E1, E2} (ties: E2 first) plus E1 and E2 alone; 20 random exits with the path's re-entry (seed offset 1000) and 20 random re-entries with the path's exits.

Primary: the prior-only path beats buy-and-hold's total return on the same sessions. Information test: it also beats the unmodified prior-only path and the median of both random families. If the primary fails: STOP, and the VIX line stays closed. If the primary passes: candidate result pending review, labelled "information test failed: not attributable to the VIX" when that test fails. Concentration reports (a)(b)(c) of protocol 1.0 are always printed. No success is claimed.

The 2009-2014 exploration is not re-run.

## 3. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start. The comparison is buy-and-hold on that span. The old figure +229.74% was buy-and-hold on 2015-07-17 → 2026-04-15; it is not a threshold.
- SPY minute bars and the VIX and VIX3M daily bars are read through `DataContext` (`DATA_SOURCE_LIST = ["SPY_1MIN", "VIX_DAILY", "VIX3M_DAILY"]`). Features are the `_prev` variant built from those bars.
- Period scores are continuous slices. The prior-only path carries the position and switches the re-entry rule, including the fresh-signal flag, at period boundaries.
- The first period uses the first listed rule (E1M1). The unmodified baseline's first period is E2none. Protocol 1.0 started the prior-only path at the second period.
- The old reproduction asserts (E1 +108.03% / 35 exits, E2 +115.60% / 12 exits on the old full span) are not repeated inside the development notebook. The span is shorter. The old-bounds calibration, run later by the queue, is the comparison with those bounds.
- No holdout evaluation is run by the agent.

## 4. Data sources

`SPY_1MIN`, `VIX_DAILY`, `VIX3M_DAILY`.

## 5. Trial budget

6 × 44 + 1 = **265**. Fewer development quarters log fewer rows. The 6 exploration trials are not repeated.

## 6. Known limitations

Everything in protocol 1.0 §1 and §10 still applies: the decision to run overrode exp08's gate, the rules carry hindsight, development data is reused, few episodes, dividends ignored, cash at 0%, informal costs. The tie order governs tied periods.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-09 | Full experiment. Prior-only +119.24% vs +229.74%, STOP. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Machinery only (§3). |
| 2.0 | 2026-10-13 | Preregister amendment, before any version 2.0 run. Scores within NUMERIC_TOLERANCE (1e-6) of the best pooled score are tied, then this protocol's tie order. A comparison counts a difference of at most 1e-6 as a match and also reports the maximum absolute difference. Summary prints show 6 decimal places. Calculations, and files later code reads, stay at full precision. |
