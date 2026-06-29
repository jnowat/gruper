import { defineConfig } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
  plugins: [sveltekit()],
  // Prevent Vite from clearing the console output.
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    // Tauri expects a fixed port; livereload over the Tauri WS bridge.
    watch: {
      ignored: ['**/src-tauri/**'],
    },
  },
  // Tauri needs its own env variables to distinguish debug/release.
  envPrefix: ['VITE_', 'TAURI_'],
});
