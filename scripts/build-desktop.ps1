# Build self-contained desktop executables for the orchestrator and agent
# runtime (WP-31), on Windows. No Docker, no PostgreSQL, no system-wide
# Python install required on the machine that RUNS the resulting .exe files —
# only this machine (the one doing the build) needs Python + pip.
#
# Usage (from the repo root, in PowerShell):
#   .\scripts\build-desktop.ps1
#
# Output: dist\gruper-orchestrator.exe and dist\gruper-agent.exe
#
# NOTE: this script mirrors scripts/build-desktop.sh step for step and was
# authored against a verified Linux build of the same PyInstaller specs (see
# ROADMAP.md WP-31 notes) — it has not been run on real Windows hardware.
# PyInstaller does not cross-compile, so the actual .exe files can only be
# produced by running this ON Windows (this repo's CI does so on a
# windows-latest GitHub Actions runner — see .github/workflows/build-windows.yml).

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvDir = if ($env:GRUPER_BUILD_VENV) { $env:GRUPER_BUILD_VENV } else { ".build-venv" }

if (-not (Test-Path $VenvDir)) {
    Write-Host "== Creating build venv at $VenvDir =="
    python -m venv $VenvDir
}

& "$VenvDir\Scripts\Activate.ps1"

Write-Host "== Installing build dependencies =="
python -m pip install --upgrade pip | Out-Null
pip install -r orchestrator/requirements.txt -r agent-runtime/requirements.txt pyinstaller | Out-Null

Write-Host "== Building orchestrator (dist\gruper-orchestrator.exe) =="
pyinstaller orchestrator/packaging/gruper-orchestrator.spec --distpath dist --workpath build --noconfirm

Write-Host "== Building agent runtime (dist\gruper-agent.exe) =="
pyinstaller agent-runtime/packaging/gruper-agent.spec --distpath dist --workpath build --noconfirm

# Stage the orchestrator AND the agent as this platform's Tauri sidecar
# binaries (WP-32, and the "Add Local Agent" flow). `cargo build`/`cargo
# tauri dev` for console/src-tauri HARD-FAILS without BOTH files present for
# the current host triple — confirmed by testing (on Linux; not yet
# re-confirmed on Windows) — Tauri's build script checks for every
# externalBin entry even for a plain debug build, not only when actually
# bundling. Any dev building the Console needs to run this script (or
# otherwise stage these files) at least once first.
if (Get-Command rustc -ErrorAction SilentlyContinue) {
    $HostTriple = (rustc -vV | Select-String '^host: (.+)$').Matches[0].Groups[1].Value
    $SidecarDir = "console/src-tauri/binaries"
    New-Item -ItemType Directory -Force -Path $SidecarDir | Out-Null
    Copy-Item "dist/gruper-orchestrator.exe" "$SidecarDir/gruper-orchestrator-$HostTriple.exe" -Force
    Copy-Item "dist/gruper-agent.exe" "$SidecarDir/gruper-agent-$HostTriple.exe" -Force
    Write-Host "== Staged Tauri sidecar binaries: $SidecarDir/{gruper-orchestrator,gruper-agent}-$HostTriple.exe =="
} else {
    Write-Host "== rustc not found — skipping Tauri sidecar staging (console build will need it) =="
}

Write-Host ""
Write-Host "== Done =="
Write-Host "  dist\gruper-orchestrator.exe  — run with no arguments; creates orchestrator.db"
Write-Host "                                  and .gruper_jwt_secret in the current directory"
Write-Host "                                  on first run, binds 127.0.0.1:8080"
Write-Host "  dist\gruper-agent.exe         — needs AGENT_ID, JWT_TOKEN, and ORCHESTRATOR_URL"
Write-Host "                                  env vars (register the agent via the orchestrator"
Write-Host "                                  REST API or the Console first)"
Write-Host ""
Write-Host "Validate the full happy path with:"
Write-Host "  python scripts\validate-desktop-packaging.py"
