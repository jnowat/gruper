// Required by @sveltejs/adapter-static: pre-render every page at build time.
// Tauri loads files from disk (no server), so SSR is disabled.
export const prerender = true;
export const ssr = false;
