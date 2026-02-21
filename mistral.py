"""Backward-compatible entrypoint for mistral."""
from llm_pipelines.mistral import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.mistral", run_name="__main__")
