import tomllib

from tests.conftest import ROOT


def test_requirements_file_matches_runtime_dependencies():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert requirements == pyproject["project"]["dependencies"]


def test_install_requirements_bat_contains_bootstrap_and_verification_steps():
    script = (ROOT / "install_requirements.bat").read_text(encoding="utf-8")

    assert "winget install --id Python.Python.3.13" in script
    assert "python -m ensurepip --upgrade" in script
    assert "python -m pip install --upgrade pip" in script
    assert "python -m pip install" in script
    assert "requirements.txt" in script
    assert "import PySide6" in script
    assert "py Tweakify.py" in script
    assert "Tweakify.pyw" in script
