import pytest
import yaml

from pyhusk.config import ServiceConfig, autodetect_services, load_config
from pyhusk.errors import PyhuskError


def write(root, rel, text=""):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_defaults_are_applied(tmp_path):
    write(tmp_path, "services/auth/main.py", "app = 1\n")
    write(tmp_path, "pyhusk.yaml", yaml.safe_dump(
        {"services": {"auth": {"entry": "services/auth/main.py"}}}
    ))
    config = load_config(tmp_path)
    service = config.services["auth"]
    assert service.app == "app"
    assert service.base_image == "python:3.12-slim"
    assert service.port == 8000
    assert service.factory is False
    assert service.registry is None
    assert service.healthcheck is None


def test_explicit_values_override_defaults(tmp_path):
    write(tmp_path, "services/pay/main.py", "app = 1\n")
    write(tmp_path, "pyhusk.yaml", yaml.safe_dump({
        "services": {
            "pay": {
                "entry": "services/pay/main.py",
                "app": "create_app",
                "factory": True,
                "base_image": "python:3.13-slim",
                "port": 9000,
                "registry": "ghcr.io/acme",
                "healthcheck": "/healthz",
            }
        }
    }))
    service = load_config(tmp_path).services["pay"]
    assert service.app == "create_app"
    assert service.factory is True
    assert service.base_image == "python:3.13-slim"
    assert service.port == 9000
    assert service.registry == "ghcr.io/acme"
    assert service.healthcheck == "/healthz"


def test_unknown_key_is_rejected(tmp_path):
    write(tmp_path, "pyhusk.yaml", yaml.safe_dump(
        {"services": {"auth": {"entry": "m.py", "prot": 8000}}}
    ))
    with pytest.raises(PyhuskError) as excinfo:
        load_config(tmp_path)
    assert "prot" in str(excinfo.value)


def test_missing_entry_file_is_rejected(tmp_path):
    write(tmp_path, "pyhusk.yaml", yaml.safe_dump(
        {"services": {"auth": {"entry": "services/auth/main.py"}}}
    ))
    with pytest.raises(PyhuskError) as excinfo:
        load_config(tmp_path)
    assert "services/auth/main.py" in str(excinfo.value)


def test_autodetect_finds_nested_fastapi_apps(tmp_path):
    write(tmp_path, "services/auth/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(tmp_path, "services/pay/main.py", "import fastapi\napp = fastapi.FastAPI()\n")
    write(tmp_path, "common/main.py", "x = 1\n")
    detected = autodetect_services(tmp_path)
    assert set(detected) == {"auth", "pay"}
    assert detected["auth"].entry == tmp_path / "services/auth/main.py"


def test_autodetect_skips_venv_build_and_dot_directories(tmp_path):
    body = "from fastapi import FastAPI\napp = FastAPI()\n"
    write(tmp_path, ".venv/lib/pkg/main.py", body)
    write(tmp_path, ".build/auth/services/auth/main.py", body)
    write(tmp_path, ".git/hooks/main.py", body)
    write(tmp_path, "services/real/main.py", body)
    assert set(autodetect_services(tmp_path)) == {"real"}


def test_load_config_falls_back_to_autodetect(tmp_path):
    write(tmp_path, "services/auth/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    config = load_config(tmp_path)
    assert set(config.services) == {"auth"}


def test_autodetect_finding_nothing_is_an_error(tmp_path):
    with pytest.raises(PyhuskError) as excinfo:
        load_config(tmp_path)
    assert "pyhusk.yaml" in str(excinfo.value)


def test_entry_outside_repo_root_is_rejected(tmp_path):
    write(tmp_path, "pyhusk.yaml", yaml.safe_dump(
        {"services": {"auth": {"entry": "../outside/main.py"}}}
    ))
    with pytest.raises(PyhuskError):
        load_config(tmp_path)


def test_service_module_path_for_uvicorn(tmp_path):
    service = ServiceConfig(entry=tmp_path / "services/auth/main.py")
    assert service.module_path(tmp_path) == "services.auth.main"
