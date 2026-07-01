# PyInstaller spec for the desktop-packaged orchestrator (WP-31).
#
# Build from the repo root:
#   pyinstaller orchestrator/packaging/gruper-orchestrator.spec
#
# Produces a single self-contained executable (dist/gruper-orchestrator[.exe])
# that needs no Python install, no Docker, and no PostgreSQL on the target
# machine — it runs against the SQLite default backend (see WP-30). Verified
# on Linux; the .exe is built by CI on a windows-latest runner (PyInstaller
# does not cross-compile), mirroring how console/'s Tauri Windows build
# already works in .github/workflows/build-windows.yml.
#
# Run via scripts/build-desktop.sh (Linux/macOS) or
# scripts/build-desktop.ps1 (Windows) rather than invoking pyinstaller
# directly — those scripts set the working directory this spec assumes.

from pathlib import Path

# PyInstaller injects SPECPATH (the directory containing this spec file)
# into the spec's exec globals at build time.
REPO_ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821

block_cipher = None

a = Analysis(
    [str(REPO_ROOT / "orchestrator" / "packaging" / "entry.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[
        (str(REPO_ROOT / "orchestrator" / "migrations"), "orchestrator/migrations"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="gruper-orchestrator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
