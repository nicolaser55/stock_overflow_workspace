# exp13_e1m1_robustness_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp13_e1m1_robustness_v2`. Config: `experiments/exp13_e1m1_robustness/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** Nicolas, 2026-10-12: this version is the frozen rule E1M1 as a single candidate. The robustness study (stress window, neighbourhood, placebo, execution) is not repeated. Its verdict stays in `docs/RESULTS_LOG.md`: E1M1 IS NOT ROBUST. No further version may follow from this result.

## 1. The frozen rule (protocol 1.0, unchanged)

E1M1 exactly as exp12 implements it. E1 is exp04's textbook trend rule (x = 0, n = 1). M1 buys back when `vix_level_prev` ≤ 0.85 × its maximum from the exit decision through now, or when the original re-entry fires, whichever is first. A missing level is false and does not enter the maximum. After an M1 re-entry a new exit waits for a fresh exit signal. No stop, no forced buy-back. Fill at the 15:59 open, $0.01/share slippage, IBKR fees, cash at 0%.

There is one candidate. Selection does not choose among rules.

## 2. What is not re-run

Protocol 1.0 steps 01 to 04: the 2005-2014 stress windows, the 36-variant neighbourhood, the four placebos, and the execution and episode checks. Their code remains in `robustness.py` and is still tested. It is not part of the development replay.

## 3. Baselines, success and stopping

Baselines, computed and not logged as trials: buy-and-hold; unmodified E1 over the same sessions; 20 random exits with E1M1's re-entry and 20 random re-entries with E1M1's exits.

The development notebook's primary comparison is buy-and-hold's total return on the development span. STOP if E1M1 does not beat it. Beating it is a candidate result pending review, not a robustness claim and not a success claim. Beating unmodified E1 and both random medians is printed as an information check. It does not replace protocol 1.0's robustness verdict.

## 4. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start.
- SPY minute bars and the VIX and VIX3M daily bars are read through `DataContext`, the same sources as exp12. Features are the `_prev` variant.
- The path is one continuous replay. With one candidate the shared selector governs every period with E1M1.
- The old reproduction targets (+314.80% / 35 exits on 2015-04-17 → 2026-04-15) are not asserted on the shorter span. The old-bounds calibration compares them later.
- No holdout evaluation is run by the agent.

## 5. Data sources

`SPY_1MIN`, `VIX_DAILY`, `VIX3M_DAILY`.

## 6. Trial budget

1 × 44 + 1 = **45**. Fewer development quarters log fewer rows. Protocol 1.0's 81 expected robustness trials are not repeated.

## 7. Known limitations

E1M1 was chosen after seeing exp12. The historical verdict is that it is not robust. Dividends ignored, cash at 0%, informal costs. This replay cannot turn the old result into out-of-sample evidence.

## 8. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-09 | Robustness study. Verdict: E1M1 IS NOT ROBUST. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Frozen E1M1 only, under the new rules. The robustness steps are not repeated (§2). |
| 2.0 | 2026-10-13 | Preregister amendment, before any version 2.0 run. One candidate, so the tie order is not used. A comparison counts a difference of at most NUMERIC_TOLERANCE (1e-6) as a match and also reports the maximum absolute difference. Summary prints show 6 decimal places. Calculations, and files later code reads, stay at full precision. |
| 2.0 | 2026-10-15 | Holdout report baselines are the development report's uninformed baselines over the span passed in, with this protocol's fixed seeds, through the point-in-time context. Report-only: no rule, grid, threshold, window, cost, baseline, selection or stopping rule changes. Development results unchanged. |
