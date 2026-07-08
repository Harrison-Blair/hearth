"""
FTHR-015: assert no secret-bearing fields in committed YAML files, and that
.env.example is secrets-only.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent

# Field names that indicate a secret at any nesting level.
SECRET_SUFFIXES = ("_api_key", "_token", "_secret", "_password")
SECRET_EXACT = {"api_key"}

# The four credential vars that MUST appear in .env.example.
REQUIRED_CRED_VARS = {
    "ASSISTANT_LLM__OPENROUTER_API_KEY",
    "ASSISTANT_LLM__OPENCODE_ZEN_API_KEY",
    "ASSISTANT_WEB_SEARCH__TAVILY_API_KEY",
    "ASSISTANT_WEB_SEARCH__EXA_API_KEY",
}


def _secret_keys(obj, path="") -> list[str]:
    """Recursively find key names that look like secrets."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            name = str(k)
            if name in SECRET_EXACT or any(name.endswith(s) for s in SECRET_SUFFIXES):
                found.append(f"{path}.{name}" if path else name)
            found.extend(_secret_keys(v, f"{path}.{name}" if path else name))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(_secret_keys(item, f"{path}[{i}]"))
    return found


def _assignment_vars(text: str) -> set[str]:
    """Return the set of VAR names from VAR=... lines (non-comment, non-blank)."""
    result = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            result.add(line.split("=", 1)[0].strip())
    return result


def test_no_secrets_in_config_yaml():
    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    bad = _secret_keys(cfg)
    assert not bad, f"config.yaml has secret-bearing fields: {bad}"


def test_no_secrets_in_default_config_yaml():
    cfg = yaml.safe_load((REPO / "default-config.yaml").read_text())
    bad = _secret_keys(cfg)
    assert not bad, f"default-config.yaml has secret-bearing fields: {bad}"


def test_env_example_contains_required_cred_vars():
    text = (REPO / ".env.example").read_text()
    defined = _assignment_vars(text)
    missing = REQUIRED_CRED_VARS - defined
    assert not missing, f".env.example missing credential vars: {missing}"


def test_env_example_has_no_non_secret_assistant_vars():
    text = (REPO / ".env.example").read_text()
    defined = _assignment_vars(text)
    assistant_vars = {v for v in defined if v.startswith("ASSISTANT_")}
    non_secret = assistant_vars - REQUIRED_CRED_VARS
    assert not non_secret, (
        f".env.example contains non-secret ASSISTANT_* vars: {non_secret}"
    )
