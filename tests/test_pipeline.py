import pytest

from pyhusk.config import load_config
from pyhusk.pipeline import resolve


@pytest.fixture
def resolved(demo_repo, venv_in, monkeypatch):
    from pyhusk.staleness import BaseRef

    repo = venv_in(demo_repo)
    # No Docker daemon in unit tests: pin the base resolution.
    monkeypatch.setattr(
        "pyhusk.pipeline.resolve_base",
        lambda ref, **_: BaseRef(reference=ref, digest="sha256:test", verified=True),
    )
    return repo, load_config(repo)


def test_resolution_slices_code_and_dependencies_together(resolved):
    repo, config = resolved
    result = resolve(repo, "a", config.services["a"])
    relative = {str(p.relative_to(repo)) for p in result.files}
    assert "services/a/main.py" in relative
    assert "services/a/security.py" in relative   # reached via Depends only
    assert "common/models.py" in relative
    assert not any(p.startswith("services/b/") for p in relative)
    assert "httpx" not in {pin.split("==")[0] for pin in result.requirements.pins}


def test_resolution_uses_a_shared_base_by_default(resolved):
    repo, config = resolved
    result = resolve(repo, "a", config.services["a"])
    assert result.base_tag is not None
    assert result.dockerfile_text.startswith(f"FROM {result.base_tag}")
    assert "pip install" not in result.dockerfile_text


def test_no_shared_base_produces_a_self_contained_dockerfile(resolved):
    repo, config = resolved
    result = resolve(repo, "a", config.services["a"], shared_base=False)
    assert result.base_tag is None
    assert "pip install" in result.dockerfile_text


def test_two_services_with_identical_deps_share_one_base_tag(resolved):
    repo, config = resolved
    # Make b's imports match a's so the dependency sets converge.
    (repo / "services/b/main.py").write_text(
        "from fastapi import FastAPI\nfrom common.models import Item\napp = FastAPI()\n"
    )
    a = resolve(repo, "a", config.services["a"])
    b = resolve(repo, "b", config.services["b"])
    assert a.base_tag == b.base_tag


def test_diverging_deps_produce_different_base_tags(resolved):
    repo, config = resolved
    a = resolve(repo, "a", config.services["a"])
    b = resolve(repo, "b", config.services["b"])
    assert a.base_tag != b.base_tag


def test_base_tag_does_not_depend_on_which_services_are_being_built(resolved):
    repo, config = resolved
    # The determinism guarantee: resolving one service alone must give the same
    # Dockerfile, and therefore the same hash, as resolving it alongside others.
    alone = resolve(repo, "a", config.services["a"])
    resolve(repo, "b", config.services["b"])
    together = resolve(repo, "a", config.services["a"])
    assert alone.dockerfile_text == together.dockerfile_text
    assert alone.slice_hash == together.slice_hash


def test_override_dockerfile_replaces_generation(resolved):
    repo, config = resolved
    (repo / "services/a/Dockerfile.override").write_text('FROM scratch\nCMD ["true"]\n')
    result = resolve(repo, "a", config.services["a"])
    assert result.dockerfile_text == 'FROM scratch\nCMD ["true"]\n'
    assert result.base_tag is None
    # The slice is still pruned; an override gets a minimal context too.
    assert not any("services/b" in str(p) for p in result.files)


def test_includes_reach_the_slice(resolved):
    repo, config = resolved
    plugin = repo / "plugins" / "late.py"
    plugin.parent.mkdir()
    plugin.write_text("from common.unused import SENTINEL\n")
    result = resolve(repo, "a", config.services["a"], includes=[plugin])
    relative = {str(p.relative_to(repo)) for p in result.files}
    assert "plugins/late.py" in relative
    assert "common/unused.py" in relative


def test_unmappable_import_becomes_a_warning(resolved):
    repo, config = resolved
    # A lazy import inside a function body. The static walk sees it, but the probe
    # never executes it, so this is the case that reaches the warning path rather
    # than failing the import outright.
    (repo / "services/a/security.py").write_text(
        "def current_user() -> str:\n"
        "    import ghost_package\n"
        "    return ghost_package.who()\n"
    )
    result = resolve(repo, "a", config.services["a"])
    assert any("ghost_package" in warning for warning in result.warnings)


def test_a_module_scope_import_error_fails_loudly(resolved):
    from pyhusk.errors import PyhuskError

    repo, config = resolved
    (repo / "services/a/main.py").write_text(
        "from fastapi import FastAPI\nimport ghost_package\napp = FastAPI()\n"
    )
    # No image is produced from an app that cannot be imported.
    with pytest.raises(PyhuskError) as excinfo:
        resolve(repo, "a", config.services["a"])
    assert "ghost_package" in str(excinfo.value)


def test_unverified_base_produces_a_warning(demo_repo, venv_in, monkeypatch):
    from pyhusk.staleness import BaseRef

    repo = venv_in(demo_repo)
    monkeypatch.setattr(
        "pyhusk.pipeline.resolve_base",
        lambda ref, **_: BaseRef(reference=ref, digest=ref, verified=False),
    )
    result = resolve(repo, "a", load_config(repo).services["a"])
    assert any("freshness" in warning or "digest" in warning for warning in result.warnings)
