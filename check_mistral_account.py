"""Backward-compatible entrypoint for check_mistral_account."""
from llm_pipelines.check_mistral_account import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.check_mistral_account", run_name="__main__")
