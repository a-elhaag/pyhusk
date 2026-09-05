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
