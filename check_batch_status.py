"""Backward-compatible entrypoint for check_batch_status."""
from llm_pipelines.check_batch_status import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.check_batch_status", run_name="__main__")
