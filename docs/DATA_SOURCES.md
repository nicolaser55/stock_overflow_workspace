# Data sources (point-in-time)

Decided by Nicolas on 2026-10-11. Every value of every dataset has an `available_ts`: the moment it could have been known.
A decision at `decision_ts` may use only values with `available_ts <= decision_ts`. Designs read data through
`so.core.point_in_time.DataContext`. In the holdout runner that is the only door, so the whole-session cut and the
perturbation check cover every source. Labels may look forward. A model trained at time t uses only rows whose
`label_known_ts` is before t (`DataContext.get_labels`).

The code and the evidence for the clocks already in the registry are in `so/core/point_in_time.py`.

## How to register a source

Add one entry to `SOURCE_SPEC_DICT` in `so/core/point_in_time.py` before any design reads the source. An unregistered
name raises. The entry has:

| Field | What to write |
|---|---|
| name | Short stable id (`SPY_1MIN`, `VIX_DAILY`, …) |
| loader | The existing function that reads the files. The holdout runner does not let a design call it. |
| time zone | `America/New_York` unless the source is stored in another zone |
| timestamp convention | What the timestamp means, with the evidence (a file, a session, a vendor note). Not an assumption. |
| availability rule | The function that adds `available_ts` to every row |
| revision policy | `not revised`, with the reason, or `vintage`: the first print is stored, and each revision is a new row with its own `available_ts` |
| role | `feature` or `label` |
| holdout | The existing guards. Development stops at the window start. The runner stops at the window end. |

When the evidence is unclear, choose the later time. The default for a 1-minute bar whose label might be the start or
the end is the start, so `available_ts = label + 1 minute`. The default for a VIX-family daily bar is that date at
16:15 America/New_York. If a daily print's release time is in doubt, use the next session's open.

`add_available_ts_pdf` stamps a frame. `get_as_of_pdf` keeps rows with `available_ts <= as_of_ts`. `DataContext.get`
is the feature door. A label source raises there. `DataContext.get_labels` keeps rows with `label_known_ts` strictly
before the cutoff. `check_feature_available_ts` raises when a feature row's `available_ts` is after its decision.

## Sources registered now

| Name | Role | Availability | Revision |
|---|---|---|---|
| `SPY_1MIN` | feature | bar start; knowable one minute later | not revised |
| `VIX_1MIN` | feature | bar start; knowable one minute later | not revised |
| `VIX_DAILY` | feature | the bar date at 16:15 New York | not revised |
| `VIX3M_1MIN` | feature | bar start; knowable one minute later | not revised |
| `VIX3M_DAILY` | feature | the bar date at 16:15 New York | not revised |
| `TSIND` | feature | end of the snapshot bar; a swing stored on its own bar waits `PA_EXTREMA_ORDER` bars (3) | not revised (cache recomputed from the bars) |
| `TSSEG` | feature | same; the snapshot shows a swing only after it is confirmed | not revised |
| `TSCTX` | feature | end of bar t; the row uses only bars `<= t` | not revised |
| `TSDAY` | feature | end of the decision bar. Forward-return columns and the after-decision columns (`fill_open`, `session_high`, `session_low`, `session_close`) are not served on this path | not revised |
| `TSDAY_FWD` | label | same TSDAY files; `label_known_ts` is the decision of session i + `LABEL_HORIZON_SESSIONS`; unfinished rows dropped | not revised |
| `TSBAR` | label | `label_known_ts` is the end of the bar where TP or SL was hit, or the end of the horizon | not revised |

The SPY evidence is the raw files: 2005-01-03 has 390 bars from 09:30 through 15:59, and the half day 2005-11-25 has
210 bars from 09:30 through 12:59. That is a start label. VIX 2005-10-03 runs 09:31 through 16:14, and VIX3M
2009-08-12 runs 09:31 through 15:59. The inventory says that label is not proven, so the same later rule is used.
VIX daily timestamps are midnight New York (observed on 2005-10-03). The decision moment is the end of the 15:58 bar,
15:59:00, which is the decision bar `so.features.daily_features` uses; the fill is the open of the next bar.

## Sources the project may add later

These are not registered and must not be downloaded until Nicolas approves the source (research-integrity rule 2).
The registration pattern is fixed now so a later design does not invent a clock after seeing results.

**Daily macro series** (a release calendar). `available_ts` is the official release time, not the period the number
describes. A figure for March that is released in April is invisible until the April release. If the agency revises
the number, the policy is `vintage`: store the first release, and store each revision as a new row with its own
`available_ts` (an ALFRED-style history). `get_as_of_pdf` returns the release that was the latest one known at the
decision, not the latest revision that exists today.

**News or text.** `available_ts` is the publish time plus a delay. The delay covers the time until the item could
actually have been seen (a wire delay, or the time until the next decision bar). A timestamp that is only a calendar
day uses the end of that day, not the open. The body is not revised in place; a correction is a new row with its own
`available_ts`.

**Dividends and T-bill rates.** `available_ts` is the announcement or publication time, not the ex-date and not the
accrual period. A dividend known only on the morning of the ex-date is not available at the previous session's 15:58
decision. A T-bill rate published with the auction result is available at that publication time. If the series is
revised, use vintage storage, as for macro data.
