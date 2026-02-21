"""Backward-compatible entrypoint for pdf_to_html."""
from llm_pipelines.pdf_to_html import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.pdf_to_html", run_name="__main__")
