"""Backward-compatible entrypoint for batch_to_structured."""
from llm_pipelines.batch_to_structured import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.batch_to_structured", run_name="__main__")
