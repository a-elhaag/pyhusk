from pyhusk.staleness import BaseRef, base_hash, slice_hash

BASE = BaseRef(reference="python:3.12-slim", digest="sha256:aaaa", verified=True)


def files_of(repo):
    return {repo / "services/a/main.py", repo / "common/models.py"}


def hash_of(repo, base=BASE, requirements="fastapi==0.115.0\n", dockerfile="FROM x\n"):
    return slice_hash(repo, files_of(repo), requirements, dockerfile, base)


def test_hash_is_stable_across_runs(demo_repo):
    assert hash_of(demo_repo) == hash_of(demo_repo)


def test_hash_changes_when_a_slice_file_changes(demo_repo):
    before = hash_of(demo_repo)
    (demo_repo / "common/models.py").write_text("# edited\n")
    assert hash_of(demo_repo) != before


def test_hash_ignores_repo_files_outside_the_slice(demo_repo):
    before = hash_of(demo_repo)
    (demo_repo / "common/unused.py").write_text("# edited, but not in the slice\n")
    assert hash_of(demo_repo) == before


def test_hash_changes_when_requirements_change(demo_repo):
    assert hash_of(demo_repo, requirements="fastapi==0.116.0\n") != hash_of(demo_repo)


def test_hash_changes_when_the_dockerfile_changes(demo_repo):
    assert hash_of(demo_repo, dockerfile="FROM y\n") != hash_of(demo_repo)


def test_hash_changes_when_the_base_digest_moves_under_a_stable_tag(demo_repo):
    moved = BaseRef(reference="python:3.12-slim", digest="sha256:bbbb", verified=True)
    # The whole point: the tag string is identical, so without the digest in the
    # hash this rebuild would never happen and the image would sit on a
    # superseded, possibly unpatched base.
    assert hash_of(demo_repo, base=moved) != hash_of(demo_repo)


def test_renaming_a_file_changes_the_hash(demo_repo):
    before = hash_of(demo_repo)
    renamed = demo_repo / "common/renamed.py"
    renamed.write_bytes((demo_repo / "common/models.py").read_bytes())
    after = slice_hash(
        demo_repo,
        {demo_repo / "services/a/main.py", renamed},
        "fastapi==0.115.0\n",
        "FROM x\n",
        BASE,
    )
    assert after != before


def test_base_hash_separates_identical_requirements_on_different_bases():
    requirements = "fastapi==0.115.0\n"
    twelve = BaseRef(reference="python:3.12-slim", digest="sha256:aaaa", verified=True)
    thirteen = BaseRef(reference="python:3.13-slim", digest="sha256:cccc", verified=True)
    # Hashing requirements alone would collide these two and hand one service the
    # other's interpreter.
    assert base_hash(twelve, requirements) != base_hash(thirteen, requirements)


def test_base_hash_collapses_identical_requirements_on_one_base():
    requirements = "fastapi==0.115.0\n"
    assert base_hash(BASE, requirements) == base_hash(BASE, requirements)


def test_base_hash_changes_with_requirements():
    assert base_hash(BASE, "a==1\n") != base_hash(BASE, "a==2\n")


def _failing_docker(monkeypatch):
    import subprocess

    from pyhusk import staleness

    monkeypatch.setattr(staleness, "_MEMO", {})
    monkeypatch.setattr(
        staleness,
        "run_docker",
        lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "429 Too Many Requests"),
    )


def _succeeding_docker(monkeypatch, digest):
    import subprocess

    from pyhusk import staleness

    monkeypatch.setattr(staleness, "_MEMO", {})
    monkeypatch.setattr(
        staleness,
        "run_docker",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, digest + "\n", ""),
    )


def test_resolve_base_writes_the_cache_on_success(tmp_path, monkeypatch):
    from pyhusk.staleness import resolve_base

    _succeeding_docker(monkeypatch, "sha256:abc")
    cache = tmp_path / "_digests.json"
    result = resolve_base("python:3.12-slim", cache=cache)
    assert result.digest == "sha256:abc"
    assert result.source == "registry"
    assert cache.exists()


def test_resolve_base_skips_the_registry_while_the_cache_is_fresh(tmp_path, monkeypatch):
    from pyhusk.staleness import resolve_base

    cache = tmp_path / "_digests.json"
    _succeeding_docker(monkeypatch, "sha256:first")
    resolve_base("python:3.12-slim", cache=cache)

    # The registry now answers differently, but the fresh cache wins, which is
    # what keeps a dev loop under the rate limit.
    _succeeding_docker(monkeypatch, "sha256:second")
    result = resolve_base("python:3.12-slim", cache=cache)
    assert result.digest == "sha256:first"
    assert result.source == "cache"


def test_resolve_base_falls_back_to_a_stale_cache_when_the_registry_fails(tmp_path, monkeypatch):
    import json
    import time

    from pyhusk.staleness import DIGEST_TTL_SECONDS, resolve_base

    cache = tmp_path / "_digests.json"
    cache.write_text(json.dumps({
        "python:3.12-slim": {"digest": "sha256:old", "at": time.time() - 2 * DIGEST_TTL_SECONDS}
    }))
    _failing_docker(monkeypatch)
    result = resolve_base("python:3.12-slim", cache=cache)
    # A registry blip must not change the hash and restale every service.
    assert result.digest == "sha256:old"
    assert result.verified is True
    assert result.source == "stale-cache"


def test_resolve_base_with_nothing_available_is_loud(tmp_path, monkeypatch):
    from pyhusk.staleness import resolve_base

    _failing_docker(monkeypatch)
    result = resolve_base("python:3.12-slim", cache=tmp_path / "_digests.json")
    assert result.verified is False
    assert result.source == "tag"
    assert result.digest == "python:3.12-slim"


def test_resolve_base_survives_a_docker_timeout(tmp_path, monkeypatch):
    import subprocess

    from pyhusk import staleness
    from pyhusk.staleness import resolve_base

    monkeypatch.setattr(staleness, "_MEMO", {})

    def hang(args, **kw):
        raise subprocess.TimeoutExpired(args, kw.get("timeout", 0))

    monkeypatch.setattr(staleness, "run_docker", hang)
    result = resolve_base("python:3.12-slim", cache=tmp_path / "_digests.json")
    assert result.source == "tag"
