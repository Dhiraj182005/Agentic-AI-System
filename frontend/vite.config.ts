import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    watch: {
      // Docker Desktop bind mounts on Windows do not deliver inotify events to
      // the container, so Vite's watcher never fires. Polling is required for
      // hot reload to pick up host edits.
      usePolling: true,
      interval: 300,
    },
  },
})
