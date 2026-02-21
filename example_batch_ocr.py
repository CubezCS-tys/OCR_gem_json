"""Backward-compatible entrypoint for example_batch_ocr."""
from llm_pipelines.example_batch_ocr import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.example_batch_ocr", run_name="__main__")
