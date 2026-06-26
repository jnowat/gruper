# Gruper Changelog

All notable changes to this project will be documented in this file.

---

## Maintenance (2026-06-15 → 2026-06-21) — Infrastructure & Documentation

No version bump — these are infrastructure, security, and documentation changes only. `APP_VERSION` remains `0.4.5`.

**Security & Dependencies:**
- UPGRADED: Chart.js 4.4.1 → 4.5.1 (latest stable)
- UPGRADED: DOMPurify 3.0.8 → 3.4.10 → 3.4.11 (latest stable; 3.4.11 fixes a `setConfig` hook leak)
- FIXED: Removed duplicate CDN `<script>` tags (was loading Chart.js and DOMPurify twice each, with mismatched SRI hashes — silent load failure in strict browsers)
- VERIFIED: All SRI integrity hashes confirmed correct via npm tarball hash computation

**Code Quality:**
- ADDED: `localStorage` `QuotaExceededError` guard in `saveState()` with retry logic and user-facing warning toast
- ADDED: 18 JS section delimiter banners across the `<script>` block for navigability (all unambiguous, version-prefix-free)
- FIXED: Shield icon tooltip now describes security features instead of showing the version tagline
- FIXED: `<noscript>` fallback added for JS-disabled browsers
- FIXED: Disambiguated duplicate `INITIALIZATION` section headers in the JS block
- FIXED: Cleaned up all legacy/version-prefixed and provenance-annotated section headers (JS and CSS blocks; 11 headers renamed across Jun 18–21, 1 redundant header removed)

**Infrastructure:**
- ADDED: `LICENSE` (MIT)
- ADDED: `.github/workflows/check.yml` — CI checks CDN reachability, JS syntax, version consistency (fatal on mismatch), and duplicate CDN tag detection
- FIXED: CI version-consistency check made fatal on actual mismatch; CDN versions now extracted dynamically from `Gruper.html`
- FIXED: Four incorrect version dates in `README.md` (wrong year 2025 → correct 2026)

**Documentation:**
- ADDED: `ROADMAP.md` — roadmap with architecture philosophy, near/medium/long-term plans, and known tech debt
- ADDED: `UserManual.md` — full user manual covering setup, agents, controls, analytics, and troubleshooting
- UPDATED: `README.md` — library versions, doc cross-links, screenshot placeholder cleanup
- UPDATED: `CHANGELOG.md` with this maintenance record

---

## v0.4.5 (2026-01-31) - Streamlined UX

**BREAKING CHANGES:**
- REMOVED: Full Gruper Analysis display (collapsible sections, word frequency, divergence detection)
- REMOVED: `toggleRoundSummary()` function (no longer needed)

**NEW FEATURES:**
- ADDED: Minimal round summary badge - simple one-liner: "📊 Round X complete • N agents responded"
- ADDED: New `.round-summary-badge` CSS class with subtle glassmorphism styling

**IMPROVEMENTS:**
- REDUCED: Round summary from ~200-300px height to ~40px
- IMPROVED: Conversation flow no longer interrupted by verbose analysis blocks
- CLEANED: Removed ~100 lines of analysis code and ~80 lines of CSS

---

## v0.4.4 (2026-01-31) - Reliability & UX Polish

**🏷️ BUG FIXES:**
- Updated all UI version displays to v0.4.4
- Fixed version inconsistencies across the application

**📝 DOCUMENTATION:**
- Removed embedded changelog from HTML
- Moved full version history to separate CHANGELOG.md file

---

## v0.4.3 (2026-01-24)

**BUG FIXES:**
- Fixed 'state.agents.find is not a function' error
- Updated page title to v0.4.3

---

## v0.4.2 (2026-01-23) - Reliability + UX Polish + Analytics + Debug Tools

**NEW FEATURES:**
- ADDED: Reliable skeleton placeholders with retry attempt tracking and time estimates
- ADDED: Collapsible round summary UI with compact design and deduplication
- ADDED: Analytics export (JSON/CSV) and enhanced empty states with axis labels
- ADDED: Debug log search filter and auto-scroll toggle with persistence
- ADDED: Version badge in footer
- ADDED: Prominent consensus toast with green border and 8s duration

**IMPROVEMENTS:**
- ENHANCED: Skeleton messages persist through retries with attempt counters
- ENHANCED: Estimated wait time shown for long-running requests (>60s)
- ENHANCED: Round summary quotes truncated to 120 chars with full text on hover
- ENHANCED: Bar charts show all agents (gray bar for zero successes)
- ENHANCED: Smooth CSS transitions for text scaling
- FIXED: Skeleton messages only removed on success or permanent failure
- IMPROVED: Debug log filtering and auto-scroll controls

---

## v0.4.1 (2026-01-22) - Timeout Control, Text Scaling, Analytics & Consensus Polish

**NEW FEATURES:**
- Global timeout control (Fast/Balanced/Patient/Custom) with per-agent overrides
- Global text scale control (80%-140%) for improved accessibility
- Resizable debug log panel with drag handle and persistent sizing
- Success rate pie chart in analytics dashboard

**IMPROVEMENTS & FIXES:**
- Analytics charts now handle empty/sparse data gracefully with placeholders
- Consensus reached now shows toast + green completion message in conversation
- Analytics auto-refreshes on conversation end (if modal open)
- Consensus flag correctly set and exported
- Removed all hardcoded model-specific timeouts

---

## v0.4.0 (2026-01-21) - Accessibility, Analytics Visuals & New Agents

**NEW FEATURES:**
- Added three new agent templates (Scientist, Psychologist, Engineer)
- Skeleton loading states replacing spinner for thinking indicators
- Chart.js analytics with response time trend and per-agent charts
- Comprehensive ARIA labels for icon-only buttons
- Semantic HTML structure (header, aside, main)
- Focus trapping for all modals
- Semi-opaque backdrops on message content & improved badge contrast
- aria-live and role attributes on messages container
- Smooth skeleton loading animations
- Enhanced text readability over glass backgrounds

---

## v0.3.0 (2024-11-21) - Stunning Glassmorphism + UX Polish

**NEW FEATURES:**
- Floating nebula particles background with smooth animation
- Animated SVG AI orb placeholder (replaced static rocket emoji)
- Message entrance animations with staggered fade-up + scale
- Premium glowing focus ring on task input with pulsing animation
- Pulsing glow on Start button when ready
- Minimizable prompt panel with toggle button
- Custom glass confirmation modals (replaced native alert/confirm)
- Enhanced visual hierarchy with depth and glow effects
- All animations respect prefers-reduced-motion
- File size: 206KB (41% under target)

---

## v0.2.0 (2024-11-20) - Production-Ready Refactor

**MAJOR IMPROVEMENTS:**
- State management with closures and clean getters/setters
- Exponential backoff (2s, 4s, 8s, 16s) for failed API calls
- Circuit breaker—agents auto-disable after 3 consecutive failures
- Security Shield icon and hardened prompt injection protection
- Chart.js lifecycle management and <80ms init performance
- Human-in-the-Loop for active user participation

---

## v0.1.7 (2024-10-31)

**BUG FIXES:**
- Fixed consensus logic bug
- Fixed tooltip z-index issues
- Fixed control panel layout

**IMPROVEMENTS:**
- Implemented DOMPurify sanitization (XSS protection)
- Enhanced security with safe HTML tag whitelist
- Converted to semantic HTML with ARIA roles
- Improved keyboard navigation

---

## v0.1.6

**IMPROVEMENTS:**
- Model-aware timeouts
- Enhanced error handling
- Consensus toggle
- IP preset switcher
- Enlarged task textarea
- Comprehensive tooltips

---

## v0.1.2

**INITIAL FEATURES:**
- Initial state management system
- Local storage persistence
