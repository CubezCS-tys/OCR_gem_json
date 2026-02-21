"""Backward-compatible entrypoint for parse_batch_results."""
from llm_pipelines.parse_batch_results import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.parse_batch_results", run_name="__main__")
