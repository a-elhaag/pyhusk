from pyhusk.graph import build_slice


def rel(repo, result):
    return {str(path.relative_to(repo)) for path in result.files}


def test_slice_follows_absolute_and_relative_imports(demo_repo):
    seeds = [demo_repo / "services/a/main.py", demo_repo / "services/a/security.py"]
    result = build_slice(demo_repo, seeds)
    files = rel(demo_repo, result)
    assert "services/a/main.py" in files
    assert "services/a/security.py" in files
    assert "common/models.py" in files


def test_slice_pulls_in_package_inits(demo_repo):
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"])
    assert "common/__init__.py" in rel(demo_repo, result)


def test_slice_excludes_the_other_service(demo_repo):
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"])
    assert not any(p.startswith("services/b/") for p in rel(demo_repo, result))


def test_slice_excludes_unimported_shared_modules(demo_repo):
    files = rel(demo_repo, build_slice(demo_repo, [demo_repo / "services/a/main.py"]))
    assert "common/unused.py" not in files
    assert "common/reporting.py" not in files


def test_service_b_pulls_reporting_and_service_a_does_not(demo_repo):
    a = build_slice(demo_repo, [demo_repo / "services/a/main.py"])
    b = build_slice(demo_repo, [demo_repo / "services/b/main.py"])
    assert "common/reporting.py" in rel(demo_repo, b)
    assert "common/reporting.py" not in rel(demo_repo, a)


def test_third_party_names_are_collected_without_stdlib(demo_repo):
    result = build_slice(demo_repo, [demo_repo / "services/b/main.py"])
    assert "fastapi" in result.third_party
    assert "httpx" in result.third_party
    assert "common" not in result.third_party
    assert "json" not in result.third_party


def test_stdlib_imports_are_ignored(demo_repo):
    (demo_repo / "services/a/main.py").write_text(
        "import json\nimport os.path\nfrom pathlib import Path\napp = None\n"
    )
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"])
    assert result.third_party == set()
    assert result.unresolved == []


def test_includes_are_added_and_walked(demo_repo):
    plugin = demo_repo / "plugins" / "extra.py"
    plugin.parent.mkdir()
    plugin.write_text("from common.unused import SENTINEL\n")
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"], includes=[plugin])
    files = rel(demo_repo, result)
    assert "plugins/extra.py" in files
    # An include is walked, not just copied: its own imports join the slice.
    assert "common/unused.py" in files


def test_from_package_import_submodule_resolves(demo_repo):
    (demo_repo / "services/a/main.py").write_text("from common import models\napp = None\n")
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"])
    assert "common/models.py" in rel(demo_repo, result)


def test_escaping_relative_import_is_reported_unresolved(demo_repo):
    (demo_repo / "services/a/main.py").write_text("from ....nowhere import thing\napp = None\n")
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"])
    assert len(result.unresolved) == 1
    assert result.unresolved[0].lineno == 1


def test_unparseable_file_is_reported_not_raised(demo_repo):
    broken = demo_repo / "services/a/broken.py"
    broken.write_text("def (((\n")
    result = build_slice(demo_repo, [demo_repo / "services/a/main.py"], includes=[broken])
    assert broken in result.unparseable
    # Still included, because the image needs the file even if we cannot read its imports.
    assert broken in result.files


def test_walk_terminates_on_circular_imports(demo_repo):
    (demo_repo / "services/a/one.py").write_text("from services.a import two\n")
    (demo_repo / "services/a/two.py").write_text("from services.a import one\n")
    result = build_slice(demo_repo, [demo_repo / "services/a/one.py"])
    files = rel(demo_repo, result)
    assert "services/a/one.py" in files
    assert "services/a/two.py" in files
