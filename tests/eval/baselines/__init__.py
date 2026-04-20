"""Baseline retrievers for the eval harness.

Each baseline implements the `RetrievalFn` protocol:
    (query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]

so it can be swapped into `run_eval(...)` and benchmarked against LV_DCP's
pipeline. Baselines live here so the comparison is version-locked with
the eval fixture.
"""
