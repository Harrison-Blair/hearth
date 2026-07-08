import pytest


@pytest.fixture(autouse=True)
def _ignore_machine_dotenv(monkeypatch):
    # Tests assert config.yaml/default behavior; a developer's real .env in
    # CWD must not leak in. Tests that exercise .env loading pass an explicit
    # Config(_env_file=...) which overrides this.
    from assistant.core.config import Config

    monkeypatch.setitem(Config.model_config, "env_file", None)
