"""Backward-compatible entrypoint for rebuild_html_simple."""
from llm_pipelines.rebuild_html_simple import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.rebuild_html_simple", run_name="__main__")
