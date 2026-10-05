"""
Stock Overflow (SO) Shared Library

    so.config       shared constants (pipeline features, execution and costs, statistics, walk-forward conventions)
    so.paths        data folders
    so.core         data loading, data quality, execution, simulators, schedule, evaluation, trial log
    so.features     feature and target builders of the data pipeline (steps 01-06)

Install once in the venv (from the workspace root): pip install -e .
Experiments live in experiments/expNN_<name>/ (a separate package, installed by the same command).
"""
