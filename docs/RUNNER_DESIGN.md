# Point-in-time runner: design (2026-10-20, updated 2026-10-21)

*Written by the assistant for infrastructure step 4 (audit S7 raised to a blocker by Nicolas on 2026-10-19; also S1,
S2, S3, S6, S9, B6). Agreed by Nicolas on 2026-10-21, with the minute mode, the single holdout path and the extra
checks added that day.*

## The rule it enforces

At each decision moment the design is shown only what could have been seen at that moment. This is enforced by how
the design is called, not checked afterwards.

## Three parts

- **Design** (experiment code): turns what it is shown into a decision.
- **Position engine** (shared code, reviewed once): turns decisions into trades, bar by bar. Anything that needs memory
  across minutes (being in a position, the entry price, a trailing high, take-profit and stop-loss levels) lives here,
  not in design code. An engine sees bar t and its own state only.
- **Runner** (shared code): walks time forward, builds the views, calls the design and the engine, and does
  everything around a run (below).

Engines, each ported from the existing simulator and required to reproduce it exactly on tests:

| Engine | Ported from | First user |
|---|---|---|
| Fractional weight (costs, dead band, integer shares) | `so.core.fractional_exposure` | exp04-exp07 |
| Barrier trades (take-profit, stop-loss, time exit) | `so.core.trade_execution`, `so.core.backtest_simulation` | exp01 |
| Trailing stop and re-entry | `so.core.reentry_simulation` | exp02 |

An idea that needs new stateful logic gets a new engine (an infrastructure change, reviewed like any other) or runs
in the slow strict daily mode.

## Daily mode (default)

- The runner walks forward one decision moment at a time (default: every session at the end of the 15:58 bar; fill at
  the 15:59 open, the existing convention).
- At each moment it calls the design with a **view** that ends at that moment:
  - SPY bars up to the end of the decision bar;
  - every declared source with `available_ts` at or before that moment (registered sources only);
  - labels only with `label_known_ts` before that moment, and only through a separate door, for training.
  A read past the end of the view does not exist: the view is a slice that stops there. The design never receives the
  full bar arrays.
- The design may keep any state between calls (running averages, a fitted model). Because the calls come in time
  order and each view stops at its moment, that state cannot contain the future.
- The design returns a decision for its engine (for the fractional engine: a target weight, 0 = cash, 1 = fully
  invested, NaN = keep). Retraining happens inside the design on its pre-registered schedule, through the label door.

## Minute mode (agreed 2026-10-21)

For decisions at minute level (exp01's entries, about 2 million minutes x 12 candidates), where calling Python once per
minute is too slow. It keeps the rule structural:

- **Rows.** Each minute row is built only from data available at the end of that minute (the existing per-session
  caches, stamped with `available_ts`). Before the design sees them, the runner checks every row's `available_ts`
  against its decision moment; one failing row stops the run.
- **Row-local signal.** The design writes one function: rows (plus a model fitted earlier) in, one value per row out,
  where each output may depend only on its own row. The runner enforces this: it shuffles the rows before calling and
  puts the outputs back in order, and it calls twice with different shuffles and requires identical outputs. A function
  that looks at neighbouring rows (shift, rolling, cumulative sums) gives different outputs and the run stops. Rows are
  passed one session at a time to keep memory small.
- **Models.** Fitted on the pre-registered schedule through the label door (`label_known_ts` before the refit moment).
  The runner applies each model only to rows after its refit moment and before the next refit; the design does not
  choose which rows a model scores.
- **Fill.** A signal at the end of minute t fills at the open of minute t + 1.
- **Engines** turn the signals into trades. Their loops are compiled (numba, added to the locked package list) so a
  full minute-level run takes minutes, not hours.

Intraday stops driven by daily decisions (exp02) use daily mode with the trailing-stop engine.

## What the runner does around a run

- **Candidates and selection:** each candidate is its own stream; periods, pooled prior-only selection and the
  carried position are done once in shared code (no copies per experiment). Candidate-period scores are slices of
  each candidate's continuous stream (result over the period's dates, including any position carried in), minus
  buy-and-hold sliced the same way. exp01-exp03 and the old holdout scorer used fresh windows; their ports are
  labelled protocol amendments, not pure re-runs. (Decided 2026-10-21.)
- **Run guards:** a run refuses uncommitted changes in the code it uses, a missing or stale `VIEW.json`, and the
  quarantine root; a resume refuses a checkpoint from a different commit or code hash. (Decided 2026-10-21.)
- **Baselines:** buy-and-hold, constant exposure at the same average weight (daily rebalanced), and random timing
  that shuffles spell lengths (same time at each weight, same number of switches; only the timing moves). Random
  timing uses 100 fixed seeds; to count as ahead of it, a design must beat at least 95% of the draws. Placing
  switches independently does not preserve exposure and is not the baseline.
- **Trial log:** rows are written as each candidate-period is scored, before any summary is shown. Trial ids are
  stable (built from the run, candidate and period), so a resumed run never logs the same trial twice. Tested with
  several processes writing at once.
- **Checkpoints:** after each period, so a crash resumes instead of restarting.
- **Parallel:** candidates run in separate processes (8 cores).
- **Report and verdict:** one shared decision rule (the agreed "consistently match or beat" rule) and one run
  manifest (status, commit, `VIEW.json` stamp, trial ids, outputs, verdict) that the orchestrator reads. The stamp
  makes an old run reproducible after the view's edge has moved.
- **Look-ahead check on every run:** truncation and perturbation at sampled cuts run automatically, as a second line.

## Holdout evaluation uses the same runner (agreed 2026-10-21)

Nicolas's holdout evaluation calls the same runner function with the quarantine root and the evaluation token. The run
starts at the development start (warm-up, models, selection history and position carried through), and only the
holdout sessions are reported. The report's result on the never-read part of the window (after 2026-04-15) is labelled
a sanity check: about 80 sessions are too few to pass or fail a design. The separate replay path in `so.core.holdout`
is retired once the runner is calibrated, so the development result and the holdout result always come from one code
path.

## What a new experiment writes

`PROTOCOL.md`, `config.py`, and one `design.py` with: the candidate list, the declared sources, the engine and its
parameters, and the decision function (daily) or row-local signal function (minute), plus fit, for a model. No copied
replay, selection, baseline or report code.

## Build order

- 4a: the view and the daily streaming loop, the engine interface with the fractional engine, tests that a design
  reading ahead cannot.
- 4b, part 1: candidates, selection, baselines, trial logging, checkpoints, parallel runs, report, verdict, manifest,
  and the holdout evaluation through the runner.
- 4b, part 2: minute mode (row checks, row-local signal with the shuffle check, model scoring windows) and the barrier
  and trailing-stop engines, each matching its existing simulator exactly on tests.
- 4c: the template rewritten on it; exp04 (daily) ported as a calibration against its saved v2 results, then exp02
  (trailing-stop engine); differences explained before anything else is ported.
