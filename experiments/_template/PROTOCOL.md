# expNN_<name>: Protocol

*Version 1.0 (YYYY-MM-DD). Experiment name `expNN_<name>`. Config: `experiments/expNN_<name>/config.py` + `so/config.py`.
Agreed with Nicolas on YYYY-MM-DD, before any of this experiment's data was explored. After the first `validation_only`
run, any rule change is a new version with a new experiment name.*

## 1. Background and research question
What is tested, why, and what earlier experiments showed. The identity that decides success (e.g. "buys back lower than it sold").

## 2. Success criteria
Primary / comparable return / secondary / information test (the uninformed baseline the information must beat) /
statistical support (`so/core/evaluation.py`). State the minimum detectable effect you expect to face.

## 3. Data
Instrument, period, adjustments, cleaning, which pipeline steps are used, any new data source (with its timing: when is a
value known relative to the 15:58 decision?).

## 4. Rules / target / features / model
Exactly as implemented (file and function names). For every feature: what it uses up to the decision bar.

## 5. Walk-forward and selection
Schedule (embargo ≥ horizon), candidates (each logged), selection rule and tie-breaks, refit, test only after freezing.

## 6. Baselines
Same simulator, same costs. Always the uninformed version of the informed component (random / fixed choices).

## 7. Stopping rules
Signal check (base rate, two-sided, ≥ 6 months per bin, pooled validation), exploration on 2005-2014 only, walk-forward
(prior-only path vs buy-and-hold and baselines).

## 8. Reporting
After-the-fact candidates, prior-only path with baselines, time in the market, MDE, success criteria, summary trial entry.

## 9. Discipline, implementation, limitations

## 10. Change log
| Version | Date | Change |
|---|---|---|
| 1.0 | YYYY-MM-DD | Initial protocol |
