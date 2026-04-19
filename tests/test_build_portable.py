import shutil
import subprocess
import sys
from pathlib import Path

from tools.build_portable import build_portable
from tests.conftest import ROOT


def test_build_portable_creates_source_portable_folder(tmp_path: Path):
    output_dir = tmp_path / "TweakifyPortable"

    result = build_portable(project_root=ROOT, output_dir=output_dir)

    assert result == output_dir
    assert (output_dir / "Tweakify.py").exists()
    assert (output_dir / "Tweakify.pyw").exists()
    assert (output_dir / "requirements.txt").exists()
    assert (output_dir / "install_requirements.bat").exists()
    assert (output_dir / "app" / "__main__.py").exists()
    assert not (output_dir / "app" / "storage" / "legacy.py").exists()
    assert (output_dir / "tools" / "nvidiaInspector.exe").exists()
    assert (output_dir / "README.txt").exists()
    assert (output_dir / "data" / "snapshots").is_dir()
    assert (output_dir / "data" / "apply-logs").is_dir()
    assert (output_dir / "data" / "cache").is_dir()
    assert (output_dir / "data" / "plans").is_dir()
    assert (output_dir / "data" / "disabled-startup").is_dir()
    assert not (output_dir / "tests").exists()
    assert not (output_dir / "docs").exists()
    assert not (output_dir / "recovered").exists()
    assert not (output_dir / "tweakify").exists()


def test_build_portable_writes_readme_with_launch_instructions(tmp_path: Path):
    output_dir = tmp_path / "TweakifyPortable"

    build_portable(project_root=ROOT, output_dir=output_dir)
    readme = (output_dir / "README.txt").read_text(encoding="utf-8")

    assert "Python 3.13+" in readme
    assert "PySide6" in readme
    assert "install_requirements.bat" in readme
    assert "py Tweakify.py" in readme
    assert "Administrator privileges" in readme


def test_build_portable_cli_executes_from_repo_root():
    output_dir = ROOT / "TweakifyPortable"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_portable.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert "Built portable folder" in result.stdout
        assert output_dir.exists()
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)
