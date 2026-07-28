/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // 桌面端自动分配端口；本地开发用 LOCI_API_TARGET 指向实际后端。
  const apiTarget = env.LOCI_API_TARGET || env.VITE_API_TARGET || 'http://127.0.0.1:8787'

  return {
    plugins: [vue(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        // monaco 0.56 exports 把 `./*` 映到 esm `.js`，CSS 需旁路
        'monaco-editor-css': fileURLToPath(
          new URL('./node_modules/monaco-editor/min/vs/editor/editor.main.css', import.meta.url),
        ),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'happy-dom',
      include: ['src/**/*.{test,spec}.ts'],
    },
  }
})
