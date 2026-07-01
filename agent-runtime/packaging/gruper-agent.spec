# PyInstaller spec for the desktop-packaged agent runtime (WP-31).
#
# Build from the repo root:
#   pyinstaller agent-runtime/packaging/gruper-agent.spec
#
# Produces a single self-contained executable (dist/gruper-agent[.exe]) that
# needs no Python install on the target machine. agent-runtime's flat module
# layout (config.py, ws_client.py, etc. imported directly, not as a package)
# means main.py can be bundled as the entry script with no wrapper needed —
# unlike the orchestrator, which needs its ASGI app imported as an object
# rather than passed to uvicorn as a string (see orchestrator/packaging/entry.py).
#
# Run via scripts/build-desktop.sh (Linux/macOS) or
# scripts/build-desktop.ps1 (Windows) rather than invoking pyinstaller
# directly — those scripts set the working directory this spec assumes.

from pathlib import Path

# PyInstaller injects SPECPATH (the directory containing this spec file)
# into the spec's exec globals at build time.
REPO_ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821
AGENT_DIR = REPO_ROOT / "agent-runtime"

block_cipher = None

a = Analysis(
    [str(AGENT_DIR / "main.py")],
    pathex=[str(AGENT_DIR)],
    binaries=[],
    datas=[],
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
    name="gruper-agent",
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
