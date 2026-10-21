# Runner design (point-in-time)

Decided with Nicolas for infrastructure step 4. Step **4a** is the view, the daily streaming loop, and the
fractional-weight engine. Step **4b** (not built here) is minute mode plus the barrier and trailing-stop engines.
This file is the interface those later pieces have to fit.

The runner is `so.runner`. It sits on `so.core.point_in_time` (the registry and `DataContext`) and does not copy
those rules. It does not load files, it does not read the holdout, and it does not call `so.core.holdout`. The caller
hands it bar arrays and a `DataContext` already loaded. Experiments, the template, and the holdout evaluator stay as
they are until a later step wires them.

## 1. Decision moment

Default (daily mode): the end of the session decision bar. On a full day that bar is labelled 15:58, so the moment is
15:59:00. The fill is the open of the next bar (15:59). Half days use the second-to-last bar, the same rule as
`so.features.daily_features.get_session_decision_idx_dict` and `so.core.point_in_time.get_decision_ts`.

`available_ts` of a 1-minute bar is the bar-start label plus one minute. A decision at `decision_ts` may use a bar
whose `available_ts` is at or before that moment. The fill bar itself is not knowable yet: it is not in the view.

The last session of a window has no design call. The engine sells every share at that session's last close, as
`so.core.fractional_exposure` already does.

## 2. The view (4a)

At each decision the design receives a `DecisionView`, not the runner's bar arrays.

The view stops at that moment:

| Door | Cut |
|---|---|
| SPY bars | array **slices** through the decision bar (inclusive). Not copies. The arrays are read-only. |
| Feature source | `DataContext.get`, `available_ts <=` the moment. `as_of` after the moment raises. |
| Label source | `DataContext.get_labels` only. `label_known_ts` strictly before the moment. A cutoff after the moment raises. |

`get` and `get_labels` default to the decision moment. An earlier cutoff is allowed. The view does not stamp clocks
itself: it uses the registry functions already on `DataContext`.

The slice of `session_end_idx_arr` for the live session is the decision bar, not the session close. That one short
integer array is a copy, because a view of the runner's `session_end_idx_arr` would point past the bar slice. Price
and timestamp arrays stay slices of the runner's arrays.

The design has no path to the full arrays. A later bar is not in the slice (an index past the last bar raises). A
later feature row is not returned. A label whose clock is the decision moment or later is not returned.

## 3. Daily streaming loop (4a)

`so.runner.run_daily_dict`. One pass over the window sessions.

1. Buy `initial_weight` at the 10:00 open of the first session (the same first-entry bar as buy-and-hold).
2. For every session except the last: build the view at the decision bar, call `design.decide(view)`, hand the
   decision to the engine, fill at the 15:59 open when the engine wants a fill.
3. On the last session: do not call the design. The engine liquidates at the last close.
4. Mark cash + shares × session close after every session, including the last.

The loop never walks every minute bar. Direct loader calls are blocked for the duration of the run
(`set_direct_read_blocked_bool`), the way the holdout runner already does.

Weight 1 throughout, with `initial_weight = 1`, reproduces buy-and-hold exactly: one buy at the first 10:00 open, no
rebalance, one sale at the last close.

Two runs on the same arrays, context, design and engine give the same trades, marks and target weights.

## 4. Minute mode (4b, not built)

The same view and the same engine interface. The loop is different.

Every bar is a decision moment: the view cuts at that bar's end (`available_ts` of that bar). The fill, if any, is
the open of the next bar in the same session. `design.decide` may be called on every bar. After each bar the loop
calls `engine.process_bar` so a working stop or target can fill intra-session, including on bars that were not
decision bars.

Daily mode does not call `process_bar`. A 4b engine that needs intra-session fills therefore runs in minute mode, or
a later daily walk that calls `process_bar` on the bars after the fill is added without changing the engine methods.

`run_minute_dict` is not in 4a. `MODE_MINUTE_STR` is reserved.

## 5. Engine interface (4a built; 4b engines not built)

The design decides. The engine fills. The loop is the only caller of the engine.

```
Engine
    open_window(fill_event, initial_weight)   first 10:00 buy
    apply_decision(fill_event, decision, decision_close)   15:59 rebalance (daily)
    process_bar(bar_event)                    no-op in 4a; 4b stops and targets
    close_session(mark_event)                 mark to market at the session close
    close_window(fill_event)                  END sale at the last close
    get_result_dict()                         trades, daily equity, metrics
```

A **fill event** has `bar_idx`, `timestamp`, `raw_price` (the open, except END which is the close). A **mark event**
has `session_date` and `close`. A **bar event** (4b) has `bar_idx`, `timestamp`, `open`, `high`, `low`, `close`.

A **decision** is a dict (or a float, which means `target_weight`):

| Field | 4a | 4b |
|---|---|---|
| `target_weight` | used; NaN / omitted = keep | optional |
| `stop_price` | ignored | barrier stop |
| `take_profit_price` | ignored | barrier target |
| `trail_multiple` | ignored | trailing stop, in the units `so.core.reentry_simulation` already uses |
| `flatten_bool` | ignored | exit at the next fill the engine allows |

Long only, unlevered: a weight is clamped to `[0, 1]`. The engine never looks at bars past the event it was given.

### Fractional-weight engine (4a)

Same rules as `so.core.fractional_exposure.simulate_fractional_exposure_dict`:

- `w` in `[0, 1]`; cash earns 0%.
- Rebalance only when `|w* − w_now| > dead_band`, at the fill open. `w_now` is shares × decision close / equity at
  that close.
- `w* >= 1` buys every affordable share; `w* <= 0` sells everything; otherwise
  `floor(w* × equity / fill open)`.
- Buys pay `ENTRY_SLIPPAGE_PER_SHARE`, sells `MARKET_EXIT_SLIPPAGE_PER_SHARE`, every order pays the IBKR fixed fee
  of `so.core.trade_execution`.
- Daily equity = cash + shares × session close.

`process_bar` is a no-op. `stop_price`, `take_profit_price`, `trail_multiple` and `flatten_bool` are ignored.

### Barrier engine (4b, not built)

One position, long only. `apply_decision` or a minute-mode `decide` may enter. `process_bar` resolves the open
trade with `so.core.trade_execution.resolve_entry_trade_dict` (SL / TP / time limit, same as the TSBAR labels).
Does not use `target_weight`.

### Trailing-stop engine (4b, not built)

The invested/cash state machine of `so.core.reentry_simulation`. `process_bar` (or the daily fill) updates the trail
and exits when it is hit. Re-entry is a later `decide`. Does not use `target_weight` except as an optional "in the
market" flag if a later design wants one.

## 6. Design contract (4a)

The design object has `decide(view) -> decision`. A callable is accepted as `decide`. `DATA_SOURCE_LIST` is the
declared sources when the runner has to build a context; a missing list is `["SPY_1MIN"]`, the same default as
`get_declared_source_name_list`.

The design reads only through the view. It does not keep a reference to bar arrays from a previous call. A cache
keyed on anything the view did not return is a look-ahead; 4a does not try to detect that beyond the view cut.

## 7. What 4a does not do

- No minute loop, no barrier engine, no trailing-stop engine.
- No change to experiments, `experiments/_template`, or `so.core.holdout`.
- No real-data run. No disk load inside `so.runner`.
- No holdout truncation test, no ledger row, no trial-log row.

## 8. Tests (synthetic only)

`tests/test_runner.py`, data root from `tests/temporary_data_root.py`:

1. A design that asks for a bar, a feature source, or a label past its moment cannot get that data.
2. Weight 1 throughout reproduces buy-and-hold exactly.
3. Two identical runs give identical results.
4. Perturbing every bar after a session's decision bar leaves every earlier decision unchanged.
