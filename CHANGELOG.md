# Gruper Changelog

All notable changes to this project will be documented in this file.

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

## v0.4.4 (2026-01-31) - UI Polish

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
