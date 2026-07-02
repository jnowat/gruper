// The engine (orchestrator sidecar) version this console build ships with.
//
// Why this exists: the Tauri shell adopts ANY process already answering
// /v1/health on the default port — including an orchestrator left running by
// a PREVIOUS install. Every server-side fix in a new build silently does
// nothing in that state, which real Windows testing surfaced as "the bugs
// I was told were fixed are still happening". The console compares this
// constant against GET /v1/health's version after connecting and shows a
// banner when they differ. Bump it in lockstep with
// orchestrator/config.py::orchestrator_version.
export const EXPECTED_ENGINE_VERSION = 'gd-0.3.0';
