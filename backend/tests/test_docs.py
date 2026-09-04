"""Documentation must not drift from the code it describes."""

from __future__ import annotations

import pathlib

import pytest

DOCS = pathlib.Path(__file__).resolve().parents[2] / "docs"
REPO = pathlib.Path(__file__).resolve().parents[2]


def test_generated_agent_doc_matches_the_code():
    from app.tools.gen_docs import agents_markdown
    current = (DOCS / "agents.md").read_text()
    assert current.strip() == agents_markdown().strip(), (
        "docs/agents.md is stale - run `python -m app.tools.gen_docs`")


def test_generated_provider_doc_matches_the_registry():
    from app.tools.gen_docs import providers_markdown
    current = (DOCS / "providers-generated.md").read_text()
    assert current.strip() == providers_markdown().strip(), (
        "docs/providers-generated.md is stale - run `python -m app.tools.gen_docs`")


@pytest.mark.parametrize("name", [
    "architecture.md", "agents.md", "providers.md", "evidence.md", "risk-engine.md",
    "performance.md", "reliability.md", "demo.md", "api.md", "judge-qa.md",
    "limitations.md", "research-inputs.md",
])
def test_every_referenced_document_exists(name):
    assert (DOCS / name).exists(), f"docs/{name} is linked from the README but missing"


def test_readme_links_resolve():
    readme = (REPO / "README.md").read_text()
    import re
    for target in re.findall(r"\]\((docs/[^)]+)\)", readme):
        assert (REPO / target).exists(), f"README links to missing {target}"


def test_env_example_documents_every_setting():
    """A setting that is not in .env.example is a setting nobody will find."""
    from app.config.settings import Settings
    example = (REPO / ".env.example").read_text().upper()
    undocumented = []
    for field in Settings.model_fields:
        if field in ("app_name", "app_long_name", "version"):
            continue          # identity, not operator-tunable
        if f"ORCA_{field.upper()}" not in example:
            undocumented.append(field)
    assert not undocumented, f"undocumented settings: {undocumented}"


def test_disclaimer_reaches_the_user_not_just_the_docs():
    from app.safety.risk_engine import DISCLAIMER
    assert "not a certified" in DISCLAIMER.lower()
    assert "IMD" in DISCLAIMER and "INCOIS" in DISCLAIMER
