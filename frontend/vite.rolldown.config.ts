/// <reference types="vitest/config" />
/**
 * Rolldown 试构建：与默认 vite 并行，不替换日常 dev。
 * bun run build:rolldown
 */
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'rolldown-vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.LOCI_API_TARGET || env.VITE_API_TARGET || 'http://127.0.0.1:8787'

  return {
    plugins: [vue(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
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
    build: {
      outDir: 'dist-rolldown',
      emptyOutDir: true,
    },
  }
})
