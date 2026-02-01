# Gruper

**Advanced Multi-Agent AI Conversation System - Production Grade**

Gruper is a sophisticated web-based application that enables collaborative conversations between multiple AI agents powered by local LLM services. Deploy up to 6 AI agents with distinct personalities to analyze problems, debate solutions, and reach consensus on complex topics.

[![Version](https://img.shields.io/badge/version-0.4.5-blue.svg)](https://github.com/jnowat/gruper)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Features

### Multi-Agent Conversations
- **Up to 6 configurable AI agents** that can interact and debate topics
- **12 pre-built agent templates**: Analyst, Creative, Critic, Synthesizer, Expert, Devil's Advocate, Philosopher, Economist, Ethicist, Scientist, Psychologist, and Engineer
- **Intelligent memory system** maintains conversation context across rounds (configurable depth)
- **Consensus checking** can automatically end conversations when agents reach agreement

### Advanced Configuration
- **Per-agent customization** of temperature, top-p, top-k, repeat penalty
- **Configurable timeouts** (global + per-agent overrides) from 60s to 3600s for slow models or hardware
- **Global text scaling** (80%-140%) for accessibility and readability
- **Max tokens and context length settings** for each agent
- **Seed control** for reproducible results
- **Custom stop sequences** per agent

### User Experience
- 📄 **Single-file architecture** - just open in a browser
- 🌓 **Dark mode support** with system preference detection
- 📑 **Multi-conversation tabs** for managing multiple sessions
- ⌨️ **Command palette** (Cmd+K) with keyboard shortcuts
- 🔌 **Real-time connection monitoring** for Ollama/LocalAI backends
- 📊 **Analytics dashboard** with interactive Chart.js visualizations (line, bar, pie charts), CSV/JSON export, and context-aware empty states
- 🔍 **Searchable debug log** with live filtering, auto-scroll toggle, and drag-to-resize pane
- 💾 **Export/import** conversations and configurations
- 🤝 **Consensus detection UI** with prominent toast notifications and visual completion markers
- 💀 **Intelligent skeleton loading** with retry tracking, estimated wait times, model names, and analytics-based predictions

### Security & Accessibility
- **DOMPurify XSS protection** for safe HTML rendering
- **Semantic HTML** with ARIA roles
- **Keyboard navigation** and focus management
- **Reduced motion support** for accessibility

## Screenshots

*Coming soon: Visual examples of Gruper's stunning glassmorphism interface*

### Suggested Screenshots
- **`gruper-main-interface.png`**: Multi-agent conversation in progress with glassmorphism design, nebula particle background, and skeleton loading indicators
- **`gruper-agent-config.png`**: Sidebar configuration panel showing 12 agent templates, timeout settings, and advanced parameters
- **`gruper-analytics-dashboard.png`**: Interactive Chart.js dashboard with response time trends, per-agent performance bars, and success rate pie chart
- **`gruper-round-summary.png`**: Minimal round summary badge showing completion status
- **`gruper-debug-console.png`**: Searchable, resizable debug log pane with live filtering and auto-scroll toggle

## Quick Start

### Prerequisites
- A modern web browser (Chrome, Firefox, Safari, Edge)
- [Ollama](https://ollama.ai/) or [LocalAI](https://localai.io/) running locally

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/jnowat/gruper.git
   cd gruper
   ```

2. **Open Gruper.html in your browser**:
   ```bash
   open Gruper.html
   # or
   firefox Gruper.html
   # or simply double-click the file
   ```

3. **Configure your LLM backend**:
   - Start Ollama: `ollama serve`
   - Or start LocalAI with your preferred configuration

4. **Connect and start conversing**:
   - Enter your Ollama/LocalAI endpoint URL (default: `http://localhost:11434`)
   - Select models for your agents
   - Enter a task and click "Start Conversation"

## Usage

### Setting Up Agents

1. **Open the sidebar** to configure agents
2. **Enable agents** (1-6) using the toggle switches
3. **Select models** from your Ollama installation
4. **Choose templates** or customize personalities
5. **Adjust parameters** (temperature, top-p, etc.) for desired behavior

### Starting a Conversation

1. Enter your task or question in the text area
2. Configure conversation settings:
   - **Max Rounds**: Limit total conversation rounds (1-50)
   - **Memory**: Enable to maintain context across rounds
   - **Consensus**: Enable to auto-stop when agents agree
3. Click **"Start Conversation"** or press `Ctrl+Enter`

### Agent Templates

- **Analyst**: Data-driven, logical, focuses on facts and evidence
- **Creative**: Innovative, imaginative, explores unconventional solutions
- **Critic**: Skeptical, thorough, identifies flaws and weaknesses
- **Synthesizer**: Integrative, diplomatic, finds common ground
- **Expert**: Knowledgeable, precise, provides authoritative insights
- **Devil's Advocate**: Contrarian, challenging, questions assumptions
- **Philosopher**: Examines principles, ethics, and deeper implications
- **Economist**: Analyzes incentives, costs, and economic impacts
- **Ethicist**: Evaluates fairness, equity, and moral dimensions
- **Scientist**: Empirical, hypothesis-testing, evidence-based
- **Psychologist**: Behavioral, motivational, bias-aware
- **Engineer**: Practical, technical, optimization-focused

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Start conversation |
| `Ctrl+P` | Pause conversation |
| `Ctrl+.` | Stop conversation |
| `Ctrl+R` | Reset conversation |
| `Ctrl+E` | Export conversation |
| `Ctrl+A` | Open analytics |
| `Ctrl+D` | Toggle debug mode |
| `Cmd+K` | Open command palette |
| `Ctrl+T` | New conversation tab |
| `Ctrl+Shift+D` | Toggle dark mode |
| `Ctrl+B` | Toggle sidebar |

## Configuration

### Timeout Settings
- **Global Timeout**: Set default timeout for all agents (Fast: 180s, Balanced: 300s, Patient: 600s, Very Patient: 900s, or Custom: 60-3600s)
- **Per-Agent Override**: Override global timeout for specific agents in Advanced Parameters
- **Use Case**: Increase timeouts for slow models (reasoning models, large models) or laptop hardware

### Text Size Control
- **Global Scaling**: Adjust text size from 80% to 140% for better readability
- **Location**: Text size control in header (near dark mode toggle)
- **Responsive**: Auto-suggests 90% scaling on screens <1000px wide
- **Accessibility**: Helps users with visual impairments or preference for larger/smaller text

### Memory Settings
- **Enabled**: Toggle conversation memory on/off
- **Depth**: Number of previous rounds to remember (1-20)

### Consensus Settings
- **Enabled**: Toggle consensus detection on/off
- **Strategy**: Keyword-based consensus detection
- **Threshold**: Agreement threshold (0-1)

### Agent Parameters

Each agent can be individually configured:

| Parameter | Range | Description |
|-----------|-------|-------------|
| Temperature | 0-1 | Controls randomness (higher = more creative) |
| Top-P | 0-1 | Nucleus sampling threshold |
| Top-K | 1-100 | Limits vocabulary selection |
| Repeat Penalty | 0.5-2 | Penalizes repetition |
| Max Tokens | 128-8192 | Maximum response length |
| Context Length | 512-16384 | Context window size |
| Seed | Optional | For reproducible results |

## Technologies

- **Frontend**: HTML5, CSS3, Vanilla JavaScript (ES6+)
- **Libraries**:
  - [Chart.js](https://www.chartjs.org/) v4.4.1 - Analytics visualization
  - [DOMPurify](https://github.com/cure53/DOMPurify) v3.0.8 - XSS protection
- **Backend Integration**: Ollama or LocalAI APIs (REST)
- **Storage**: LocalStorage for state persistence

## Analytics

Track conversation metrics in real-time:
- **Total rounds** completed
- **Messages** sent and received
- **Response times** per agent
- **Success rate** of API calls
- **Model usage** statistics

## Troubleshooting

### Connection Issues
- Ensure Ollama/LocalAI is running: `ollama serve`
- Check the endpoint URL (default: `http://localhost:11434`)
- Verify CORS settings if using a remote server
- Use the IP preset switcher for common configurations

### Performance
- Adjust model-aware timeouts for slower models
- Reduce context length for faster responses
- Lower max tokens if responses are taking too long
- Enable memory only when needed

### Debug Mode
- Press `Ctrl+D` to toggle debug logging
- Check browser console for detailed error messages
- Export conversation data for analysis

## Version History

### v0.4.5 (2026-01-31) - Streamlined UX
- 📊 **Simplified Round Summary**: Replaced verbose Gruper Analysis with minimal badge ("📊 Round X complete • N agents responded")
- 🧹 **Removed Clutter**: Eliminated collapsible sections, word frequency analysis, divergence detection, and generic questions
- ⚡ **Faster Rendering**: Lightweight badge reduces DOM complexity and improves performance
- 🎨 **Cleaner UI**: Subtle, non-intrusive design that doesn't interrupt conversation flow

### v0.4.4 (2026-01-31) - Reliability & UX Polish
- 🏷️ **Version Displays**: Updated all UI version strings to "v0.4.4 - Reliability & UX Polish" in header, footer, and title
- 💀 **Enhanced Skeletons**: Show model names in thinking indicators ("Thinking… (Model: mistral:7b)"), analytics-based time estimates, 30s estimate updates, overdue status for long-running requests
- ✨ **Polish**: Smooth fade-in animation for skeletons (0.3s), flash yellow highlight for new debug entries (1s), dismissible consensus banner with close button
- 🎯 **Accuracy**: Improved estimate calculations using historical response times per model from analytics data

### v0.4.3 (2026-01-24) - Bug Fixes
- 🐛 **Critical Fix**: Resolved "state.agents.find is not a function" error by using Object.values() for object iteration
- 📝 **Update**: Changed page title to reflect v0.4.3

### v0.4.2 (2026-01-23) - Reliability + UX Polish + Export
- 💀 **Reliable Skeleton Placeholders**: Show skeleton on every attempt including retries, display attempt number (e.g., "Attempt 2/5"), show estimated wait time for requests >60s
- 📊 **Round Summary Improvements**: Compact spacing, collapsible sections (auto-collapse >3 divergences), deduplicated quotes, 120-char truncation with hover tooltips, agent avatars for visual recognition
- 📈 **Analytics Enhancements**: Per-chart empty states with specific guidance, axis labels (X="Round/Agent", Y="Seconds"), export to CSV/JSON with detailed metrics
- 🔍 **Debug Log Usability**: Live search filter (case-insensitive), auto-scroll toggle with localStorage persistence, better log visibility
- ✨ **Polish**: Prominent consensus toast (green border, 8s duration, enhanced glow), version badge in footer, smooth font-size transitions (0.2s ease)
- 🧹 **Code Quality**: Better skeleton lifecycle management, progress tracking cleanup, improved chart tooltips

### v0.4.1 (2026-01-22) - Timeouts + Text Scaling + Analytics Polish
- ⏱️ **Configurable Timeouts**: Global timeout control (Fast/Balanced/Patient/Custom 60-3600s) + per-agent overrides
- 🔤 **Text Scaling**: Global font size control (80%-140%) for accessibility, auto-suggests 90% on mobile
- 📊 **Analytics Improvements**: Empty-state handling, success rate pie chart, auto-refresh on conversation end, exclude failed responses
- ✅ **Consensus UI**: Toast notifications, green completion message, proper export flag, visual feedback
- 📏 **Resizable Debug Log**: Drag-to-resize pane with expand/collapse button, persisted height
- 🧹 **Code Quality**: Removed hardcoded model timeouts, cleaner timeout system with helper function

### v0.4.0 (2025-11-21) - Accessibility + Analytics + New Agents
- ♿ **Accessibility Overhaul**: ARIA labels, focus trapping, semantic HTML, improved contrast
- 📊 **Chart.js Analytics**: Interactive line/bar charts for response times and agent performance
- 💀 **Skeleton Loading**: Modern animated placeholders replace spinner indicators
- 🎭 **3 New Agent Templates**: Scientist, Psychologist, Engineer
- 🎨 **Enhanced Contrast**: Semi-opaque backdrops on messages, improved badge visibility
- 🔒 **Focus Management**: Full keyboard navigation with modal focus trapping
- ⚡ **Chart Lifecycle**: Proper Chart.js creation/destruction prevents memory leaks
- 📐 **Semantic Structure**: Header, aside, main tags for better screen reader support

### v0.3.0 (2025-11-21) - Stunning Glassmorphism
- ✨ Floating nebula particles background with smooth animation
- ✨ Animated SVG AI orb placeholder (replaced static rocket emoji)
- ✨ Message entrance animations with staggered fade-up + scale
- ✨ Premium glowing focus ring on task input with pulsing animation
- ✨ Pulsing glow on Start button when ready
- 🎨 Minimizable prompt panel with toggle button
- 🎨 Custom glass confirmation modals (replaced native alert/confirm)
- 🎨 Enhanced visual hierarchy with depth and glow effects
- ⚡ All animations respect prefers-reduced-motion
- ⚡ File size: 206KB (41% under target)

### v0.2.0 (2025-11-20) - Production-Ready Refactor
- 🔧 State management refactor with closures
- 🔧 Exponential backoff (2s, 4s, 8s, 16s) for failed API calls
- 🔧 Circuit breaker—agents auto-disable after 3 consecutive failures
- 🛡️ Security Shield icon and hardened prompt injection protection
- ⚡ Chart.js lifecycle management (prevent memory leaks)
- ⚡ Optimized init <80ms even with 500 messages
- 🎯 Human-in-the-Loop for active user participation

### v0.1.7 (2025-10-31)
- ✓ Fixed consensus logic bug
- ✓ Fixed tooltip z-index issues
- ✓ Fixed control panel layout
- ✓ Implemented DOMPurify sanitization (XSS protection)
- ✓ Enhanced security with safe HTML tag whitelist
- ✓ Converted to semantic HTML with ARIA roles
- ✓ Improved keyboard navigation

### v0.1.6
- ✓ Model-aware timeouts
- ✓ Enhanced error handling
- ✓ Consensus toggle
- ✓ IP preset switcher
- ✓ Enlarged task textarea
- ✓ Comprehensive tooltips

### v0.1.2
- ✓ Initial state management system
- ✓ Local storage persistence

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests. Better yet, fork it and go for it, I have so little clue what's going on and even less time.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues, questions, or feature requests, please open an issue on [GitHub](https://github.com/jnowat/gruper/issues).

---

**Built with ❤️ for the AI community**
...thanks, Claude! <3
