import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // UXAgent API uses 8081; 8000 and 8100 are model SSH tunnels.
      '/run': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
        secure: false
      },
      '/progress': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
        secure: false
      },
    }
  }
})
