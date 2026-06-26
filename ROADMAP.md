# Gruper Roadmap

Current version: **v0.4.5 — Streamlined UX**

This roadmap reflects the project's current trajectory and known improvement areas. Because Gruper is a single-file, zero-build application, priorities are weighted toward high-value changes that preserve that simplicity rather than adding tooling overhead.

---

## Architecture Philosophy

Gruper's single-file model (`Gruper.html`) is **intentional and permanent** for the foreseeable future. The entire application — HTML, CSS, and JavaScript — ships as one file you double-click to open. No install, no server, no build step.

This means:
- Feature additions happen inside `Gruper.html`
- External dependencies stay CDN-loaded (Chart.js, DOMPurify)
- State lives in `localStorage`
- There is no bundler, transpiler, or package manager

The single-file ethos becomes a constraint if/when `Gruper.html` grows beyond ~500 KB or the JavaScript block exceeds ~5,000 lines and navigability becomes painful. We are not near those limits yet (~260 KB / ~3,370 JS lines as of v0.4.5), but this is worth tracking.

---

## Completed ✅

| Date | Item |
|------|------|
| 2026-06-15 | Remove duplicate CDN script tags (critical bug — silent load failure in strict browsers) |
| 2026-06-15 | Upgrade Chart.js 4.4.1 → 4.5.1 (latest stable) |
| 2026-06-15 | Upgrade DOMPurify 3.0.8 → 3.4.10 (security library) |
| 2026-06-15 | Add MIT `LICENSE` file |
| 2026-06-15 | Add GitHub Actions CI workflow (`check.yml`) |
| 2026-06-15 | Add `localStorage` `QuotaExceededError` guard in `saveState()` |
| 2026-06-15 | Add JS section delimiter banners across 3,329-line script block |
| 2026-06-15 | Fix shield icon tooltip (was showing version tagline, now shows security features) |
| 2026-06-16 | Harden CI version-consistency check (fatal on mismatch, dynamic CDN version extraction) |
| 2026-06-17 | Add `<noscript>` fallback for JS-disabled browsers |
| 2026-06-17 | Disambiguate duplicate `INITIALIZATION` section headers in JS block |
| 2026-06-17 | Verify all SRI hashes via npm tarball (confirmed correct) |
| 2026-06-17 | Upgrade DOMPurify 3.4.10 → 3.4.11 (maintenance patch) |
| 2026-06-18 | Clean up legacy/version-prefixed JS section headers (4 sections renamed, 1 redundant removed) |
| 2026-06-19 | Create `ROADMAP.md` (this file) |
| 2026-06-19 | Create `UserManual.md` |
| 2026-06-19 | Add `CHANGELOG.md` maintenance section for June 2026 infrastructure work |
| 2026-06-19 | Clean up README screenshot placeholder; add doc cross-links |
| 2026-06-20 | Rename JS section headers: `UI RENDERING` → `SIDEBAR & AGENT CONFIG`, `CONVERSATION ENGINE` → `TASK INPUT & VALIDATION`, two version-prefixed headers cleaned |
| 2026-06-21 | Strip remaining provenance/version annotations from 7 section headers (2 CSS + 5 JS); update CHANGELOG date range; refresh ROADMAP |
| v0.4.5 | Streamlined round summary, removed verbose analysis blocks |
| v0.4.4 | Version display consistency, embedded changelog extracted |
| v0.4.3 | Critical `agents.find` bug fix |
| v0.4.2 | Skeleton placeholders with retry tracking, analytics export, debug log search |
| v0.4.1 | Configurable timeouts, text scaling (80–140%), resizable debug pane |
| v0.4.0 | Accessibility overhaul (ARIA), Chart.js analytics dashboard, 3 new agent templates |

---

## Near-term (v0.5.x)

Items with known scope and low architectural risk.

### P1 — UX & Usability

- **Conversation search** — find text across all rounds and conversations
- **Agent response diff view** — highlight where agents agree vs. diverge per round
- **Pinnable messages** — mark specific agent responses to reference later
- **Export to Markdown** — readable export format alongside the existing JSON

### P2 — Configuration

- **Agent groups / presets** — save and reload a named set of 6 agents with one click
- **Per-conversation agent overrides** — change an agent's model mid-conversation without resetting
- **More stop-sequence templates** per agent type

### P3 — Maintenance & Quality

- **Reduce inline `onclick` handlers** (~64 currently) — migrate to `addEventListener` calls for CSP compatibility and testability; can be done incrementally without breaking the single-file model
- **Add screenshot examples to README** — remove the "coming soon" placeholder
- **localStorage usage meter** — show current storage consumption and a manual clear option in the UI
- **GitHub Actions: SRI re-verification** — add step to download CDN files and re-verify SRI hashes on each push
- **GitHub Actions: line-count trend** — report `Gruper.html` line-count growth as a CI metric

---

## Medium-term (v0.6.x)

Items that are desirable but require more design work or carry higher risk.

- **Streaming responses** — stream token-by-token from Ollama instead of waiting for full completion
- **Conversation branching** — fork a conversation at a given round to explore alternative paths
- **Agent memory summaries** — compress earlier context into a structured summary when depth limit is hit, rather than truncating
- **WebSocket / SSE streaming** — real-time token-by-token output if the Ollama/LocalAI backend supports it
- **Multi-tab real-time sync** — use `BroadcastChannel` so conversations started in one tab appear in another without a page reload
- **LocalAI model discovery** — auto-populate model list from LocalAI's `/v1/models` endpoint

---

## Long-term / Architectural

- **Optional ES module build** — if the single JS block exceeds ~5,000 lines, introduce a lightweight `esbuild` / `rollup` bundler step (output is still one `.html` file) so the source can be split into logical modules without changing the distribution model
- **PWA shell** — `manifest.json` + service worker for offline use and home-screen installation
- **Tauri wrapper** (optional) — package Gruper as a native desktop app with filesystem access and tray integration; the HTML/JS core stays unchanged
- **First-run tutorial / onboarding overlay** for new users
- **Localization support (i18n)** for non-English users
- **Integration tests via Playwright** against a mock Ollama server

---

## Out of scope (intentionally)

- **Server-side component** — Gruper is and will remain a client-only app; no backend
- **Account system / cloud sync** — state stays in localStorage; sync is out of scope
- **npm/pip packages** — no package manager; CDN only
- **Framework rewrite** (React/Vue/Svelte) — not planned; vanilla JS is a feature, not a limitation

---

## Known technical debt

| Item | Severity | Notes |
|------|----------|-------|
| ~64 inline `onclick` handlers | Medium | Blocks strict CSP; refactor incrementally |
| No automated tests | Medium | Single-file architecture makes unit tests awkward; smoke tests via Playwright feasible |
| `localStorage` growth | Low | Quota guard is in place; a usage meter and trim UI would be nice |
| File size growth trend | Low | ~260 KB today; monitor monthly |
| README screenshots | Low | "Coming soon" placeholder — needs real images |

---

*Last updated: 2026-06-21 by Claude (routine review)*
*Maintained alongside `DailyClaudeRoutineCheckup.md` — review and update at each daily check.*
