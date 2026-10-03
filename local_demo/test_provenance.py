"""Optional Git provenance must not prevent offline harness execution."""

import subprocess

from local_demo.run import upstream_revision


def test_provenance_resolves_an_existing_upstream_ref(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/upstream/main", commit], cwd=tmp_path, check=True)
    assert upstream_revision(tmp_path) == commit


def test_plain_fork_without_upstream_has_unknown_provenance(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert upstream_revision(tmp_path) is None


def test_source_archive_without_git_metadata_has_unknown_provenance(tmp_path):
    assert upstream_revision(tmp_path) is None


def test_missing_git_executable_has_unknown_provenance(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr("local_demo.run.subprocess.run", unavailable)
    assert upstream_revision(tmp_path) is None
