"""Seat eval suite runner (M1 in-process; M1-BE-05 moves execution to the worker lane)."""

from .runner import SuiteRunResult, run_suite

__all__ = ["SuiteRunResult", "run_suite"]
