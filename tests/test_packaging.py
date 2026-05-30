from __future__ import annotations

from pathlib import Path


def test_packaging_assets_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "B2BInvoiceAutomation.spec").exists()
    assert (root / "packaging" / "desktop_launcher.py").exists()
    assert (root / "scripts" / "build_desktop.ps1").exists()
    assert (root / "scripts" / "install_desktop.ps1").exists()
    assert (root / "scripts" / "uninstall_desktop.ps1").exists()


def test_pyinstaller_spec_uses_windowed_desktop_exe():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "B2BInvoiceAutomation.spec").read_text(encoding="utf-8")
    assert 'name="B2B Invoice Automation"' in spec
    assert "console=False" in spec
    assert "packaging/desktop_launcher.py" in spec


def test_install_script_expands_build_output_wildcard():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "install_desktop.ps1").read_text(encoding="utf-8")
    assert 'Copy-Item -Path (Join-Path $SourceDir "*")' in script
    assert 'Copy-Item -LiteralPath (Join-Path $SourceDir "*")' not in script
