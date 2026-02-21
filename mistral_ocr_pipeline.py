"""Backward-compatible entrypoint for mistral_ocr_pipeline."""
from llm_pipelines.mistral_ocr_pipeline import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.mistral_ocr_pipeline", run_name="__main__")
