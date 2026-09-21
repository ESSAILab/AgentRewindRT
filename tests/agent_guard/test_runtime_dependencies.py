from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


REPO_ROOT = Path(__file__).resolve().parents[2]


def _dependency_names(pyproject: Path) -> set[str]:
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return {Requirement(item).name.lower() for item in config["project"]["dependencies"]}


def test_ai_agent_has_no_network_analysis_runtime_dependencies():
    names = _dependency_names(REPO_ROOT / "ai_agent" / "pyproject.toml")

    forbidden = {
        "redis",
        "elasticsearch",
        "mitreattack-python",
        "langchain-anthropic",
        "langchain-deepseek",
        "langchain-groq",
        "langchain-mcp-adapters",
        "langchain-tavily",
        "tavily-python",
        "duckduckgo-search",
        "exa-py",
        "arxiv",
        "linkup-sdk",
        "azure-search-documents",
    }
    assert names.isdisjoint(forbidden)


def test_web_ui_has_only_required_runtime_dependencies():
    names = _dependency_names(REPO_ROOT / "web_ui" / "pyproject.toml")

    assert names == {"fastapi", "uvicorn", "python-dotenv", "requests"}
