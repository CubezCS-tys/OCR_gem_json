"""Backward-compatible entrypoint for image_utils."""
from llm_pipelines.image_utils import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("llm_pipelines.image_utils", run_name="__main__")
