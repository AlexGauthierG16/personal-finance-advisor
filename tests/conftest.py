"""Shared fixtures. Every test gets its own temporary user-state file; the real
data/user_state.json must never be read or written by the test suite."""
import pytest

from backend import user_state

REAL_STATE_FILE = user_state.DEFAULT_PATH


@pytest.fixture(autouse=True)
def isolated_user_state(tmp_path, monkeypatch):
    monkeypatch.setattr(user_state, "STATE_PATH", tmp_path / "memory" / "user_state.json")


@pytest.fixture(scope="session", autouse=True)
def real_state_file_is_never_touched():
    def stamp():
        return REAL_STATE_FILE.stat().st_mtime_ns if REAL_STATE_FILE.exists() else None
    before = stamp()
    yield
    assert stamp() == before, "a test touched the real data/user_state.json"
