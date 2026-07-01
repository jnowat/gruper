#!/usr/bin/env bash
# Build self-contained desktop executables for the orchestrator and agent
# runtime (WP-31). No Docker, no PostgreSQL, no system-wide Python install
# required on the machine that RUNS the resulting executables — only this
# machine (the one doing the build) needs Python + pip.
#
# Usage (from the repo root):
#   ./scripts/build-desktop.sh
#
# Output: dist/gruper-orchestrator and dist/gruper-agent
#
# Windows equivalent: scripts/build-desktop.ps1 (same steps, PowerShell).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${GRUPER_BUILD_VENV:-.build-venv}"

if [ ! -d "$VENV_DIR" ]; then
  echo "== Creating build venv at $VENV_DIR =="
  python3 -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "== Installing build dependencies =="
pip install --upgrade pip >/dev/null
pip install -r orchestrator/requirements.txt -r agent-runtime/requirements.txt pyinstaller >/dev/null

echo "== Building orchestrator (dist/gruper-orchestrator) =="
pyinstaller orchestrator/packaging/gruper-orchestrator.spec --distpath dist --workpath build --noconfirm

echo "== Building agent runtime (dist/gruper-agent) =="
pyinstaller agent-runtime/packaging/gruper-agent.spec --distpath dist --workpath build --noconfirm

# Stage the orchestrator as this platform's Tauri sidecar binary (WP-32).
# `cargo build`/`cargo tauri dev` for console/src-tauri HARD-FAILS without
# this file present for the current host triple — confirmed by testing, not
# just documented; Tauri's build script checks for it even for a plain debug
# build, not only when actually bundling. Any dev building the Console needs
# to run this script (or otherwise stage this file) at least once first.
if command -v rustc >/dev/null 2>&1; then
  HOST_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
  SIDECAR_DIR="console/src-tauri/binaries"
  SIDECAR_NAME="gruper-orchestrator-${HOST_TRIPLE}"
  mkdir -p "$SIDECAR_DIR"
  cp "dist/gruper-orchestrator" "$SIDECAR_DIR/$SIDECAR_NAME"
  chmod +x "$SIDECAR_DIR/$SIDECAR_NAME"
  echo "== Staged Tauri sidecar binary: $SIDECAR_DIR/$SIDECAR_NAME =="
else
  echo "== rustc not found — skipping Tauri sidecar staging (console build will need it) =="
fi

echo ""
echo "== Done =="
echo "  dist/gruper-orchestrator  — run with no arguments; creates orchestrator.db"
echo "                              and .gruper_jwt_secret in the current directory"
echo "                              on first run, binds 127.0.0.1:8080"
echo "  dist/gruper-agent         — needs AGENT_ID, JWT_TOKEN, and ORCHESTRATOR_URL"
echo "                              env vars (register the agent via the orchestrator"
echo "                              REST API or the Console first)"
echo ""
echo "Validate the full happy path with:"
echo "  python scripts/validate-desktop-packaging.py"
