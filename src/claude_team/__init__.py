"""Core modules for the claude-team tooling."""

from .idle_detection import Worker, check_file_idle, detect_worker_idle, get_claude_jsonl_path, get_project_slug

__all__ = [
    "Worker",
    "check_file_idle",
    "detect_worker_idle",
    "get_claude_jsonl_path",
    "get_project_slug",
]
