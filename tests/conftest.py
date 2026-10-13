import os

os.environ["ADHAN_TESTING"] = "1"

import pytest

from app import config as config_mod


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    monkeypatch.setattr(config_mod, "CACHE_DIR", cache)
    return path
