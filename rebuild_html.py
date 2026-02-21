"""Backward-compatible entrypoint for rebuild_html."""
from llm_pipelines.rebuild_html import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.rebuild_html", run_name="__main__")
