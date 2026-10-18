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
    import app.times as times_mod

    monkeypatch.setattr(times_mod, "CACHE_DIR", cache)
    return path


@pytest.fixture(autouse=True)
def isolated_played_prayers(tmp_path, monkeypatch):
    """Never read or write the real cache/played_prayers.json from tests."""
    from app import player

    path = tmp_path / "played_prayers.json"
    monkeypatch.setattr(player, "PLAYED_PATH", path)
    return path
