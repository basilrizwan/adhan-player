"""scripts/update.sh must never replace the user's settings or recordings."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    ).stdout.strip()


def commit_files(repo, files, message):
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def run_update(device, origin, *args):
    env = {**os.environ, "ADHAN_UPDATE_URL": str(origin), "ADHAN_UPDATE_BRANCH": "main"}
    env.pop("ADHAN_UNATTENDED", None)
    return subprocess.run(
        ["bash", str(device / "scripts" / "update.sh"), "--no-restart", *args],
        cwd=device, capture_output=True, text=True, env=env,
    )


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    script = SCRIPT.read_bytes()
    commit_files(origin, {
        "scripts/update.sh": script,
        "config.json": b'{"dua_id": "from-fajr"}\n',
        "audio/adhan.mp3": b"repo-adhan",
        "audio/dua/from-fajr.mp3": b"repo-dua-v1",
        ".gitignore": b"cache/\naudio/kahf.mp3\n",
    }, "v1")
    device = tmp_path / "device"
    git(tmp_path, "clone", "-q", str(origin), str(device))

    # The user's own state on the speaker
    (device / "config.json").write_text('{"dua_id": "user-choice"}\n')
    (device / "audio" / "kahf.mp3").write_bytes(b"user-kahf")
    (device / "audio" / "adhan.mp3").write_bytes(b"user-adhan")
    (device / "audio" / "custom.mp3").write_bytes(b"user-untracked")
    return origin, device


def assert_user_state_intact(device):
    assert (device / "config.json").read_text() == '{"dua_id": "user-choice"}\n'
    assert (device / "audio" / "kahf.mp3").read_bytes() == b"user-kahf"
    assert (device / "audio" / "adhan.mp3").read_bytes() == b"user-adhan"
    assert (device / "audio" / "custom.mp3").read_bytes() == b"user-untracked"
    assert not (device / "cache" / ".update-stash").exists()


def test_update_keeps_user_files_and_adds_new_repo_files(repos):
    origin, device = repos
    commit_files(origin, {
        "config.json": b'{"dua_id": "short-authentic"}\n',
        "audio/adhan.mp3": b"repo-adhan-v2",
        "audio/dua/from-fajr.mp3": b"repo-dua-v2",
        "audio/dua/new-clip.mp3": b"repo-new",
        "app.py": b"print('v2')\n",
    }, "v2")

    res = run_update(device, origin)

    assert res.returncode == 0, res.stdout + res.stderr
    assert "UPDATED" in res.stdout
    assert git(device, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD")
    assert_user_state_intact(device)
    # The device's existing copy of a tracked clip wins over the repo's new one
    assert (device / "audio" / "dua" / "from-fajr.mp3").read_bytes() == b"repo-dua-v1"
    assert (device / "audio" / "dua" / "new-clip.mp3").read_bytes() == b"repo-new"
    assert (device / "app.py").exists()


def test_up_to_date_run_touches_nothing(repos):
    origin, device = repos
    res = run_update(device, origin)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Already up to date" in res.stdout
    assert_user_state_intact(device)


def test_interrupted_update_is_recovered_on_next_run(repos):
    origin, device = repos
    commit_files(origin, {"app.py": b"print('v2')\n"}, "v2")

    # Simulate a run that stashed, reset to the repo, then died before restoring.
    stash = device / "cache" / ".update-stash"
    stash.mkdir(parents=True)
    shutil.copy2(device / "config.json", stash / "config.json")
    shutil.copytree(device / "audio", stash / "audio")
    (stash / ".reset-in-progress").touch()
    git(device, "reset", "-q", "--hard", "origin/main")
    (device / "audio" / "kahf.mp3").unlink()
    (device / "audio" / "custom.mp3").unlink()
    assert (device / "config.json").read_text() == '{"dua_id": "from-fajr"}\n'

    res = run_update(device, origin)

    assert res.returncode == 0, res.stdout + res.stderr
    assert "Previous update was interrupted" in res.stdout
    assert_user_state_intact(device)


def test_update_that_untracks_config_keeps_user_settings(repos):
    origin, device = repos
    # The repo stops tracking config.json; git deletes it on the device during reset.
    git(origin, "rm", "-q", "--cached", "config.json")
    (origin / "config.json").unlink()
    commit_files(origin, {".gitignore": b"cache/\naudio/kahf.mp3\nconfig.json\n"}, "untrack config")

    res = run_update(device, origin)

    assert res.returncode == 0, res.stdout + res.stderr
    assert git(device, "ls-files", "config.json") == ""
    assert_user_state_intact(device)

    # Later updates leave the now-ignored file alone.
    commit_files(origin, {"app.py": b"print('v3')\n"}, "v3")
    res = run_update(device, origin)
    assert res.returncode == 0, res.stdout + res.stderr
    assert_user_state_intact(device)


def test_first_time_sd_copy_keeps_user_files(repos, tmp_path):
    origin, device = repos
    shutil.rmtree(device / ".git")

    res = run_update(device, origin)

    assert res.returncode == 0, res.stdout + res.stderr
    assert (device / ".git").is_dir()
    assert_user_state_intact(device)
