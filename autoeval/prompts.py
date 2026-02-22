from __future__ import annotations

import shutil
from pathlib import Path


PROMPTS_DIR: Path = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    prompt_path = PROMPTS_DIR / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def get_initializer_task(project_dir: Path, task: str) -> str:
    template = load_prompt("initializer_task")
    return template.format(project_dir=project_dir, task=task)


def get_continuation_task(project_dir: Path, task: str) -> str:
    template = load_prompt("continuation_task")
    return template.format(project_dir=project_dir, task=task)


def load_orchestrator_prompt() -> str:
    return load_prompt("orchestrator_prompt")


def copy_spec_to_project(project_dir: Path) -> Path:
    source = PROMPTS_DIR / "app_spec.txt"
    if not source.exists():
        raise FileNotFoundError(f"Spec file not found: {source}")
    project_dir.mkdir(parents=True, exist_ok=True)
    target = project_dir / "app_spec.txt"
    if not target.exists():
        shutil.copy(source, target)
    return target

