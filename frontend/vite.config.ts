/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { defineConfig, loadEnv } from 'vite'

/**
 * 供应商分包。不分包时 vue/router/pinia/colada/vueuse/element-plus 全落进
 * 同一个 entry chunk，改一行业务代码就让用户重下整包。
 *
 * 只给「首屏必然要加载」的依赖建组。**不要**给纯异步依赖（如
 * `vue-element-plus-x`）建组：实测 rolldown 会把这种组和首屏组合并成一个
 * chunk，反而把 270 KB 助手 UI 拽回首屏——让它自然留在 AssistantHost 的
 * 异步分片里才是对的。同理不合并 monaco / echarts 的语言与图表模块：
 * 它们已经是按需 import 的小分片，粗粒度合并会让 CodeEditor 一次拉全语言。
 *
 * 注意顺序：`@element-plus/icons-vue` 与 `element-plus` 都要落到同一组，
 * 而 `vue-element-plus-x` 因为没有前置 `/` 不会命中 `/element-plus/`。
 */
function vendorChunk(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined
  const path = id.replace(/\\/g, '/')
  if (path.includes('/element-plus/') || path.includes('/@element-plus/')) return 'vendor-element-plus'
  if (/\/(vue|@vue|vue-router|pinia|@pinia|@vueuse|comlink)\//.test(path)) return 'vendor-vue'
  return undefined
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // 桌面端自动分配端口；本地开发用 LOCI_API_TARGET 指向实际后端。
  const apiTarget = env.LOCI_API_TARGET || env.VITE_API_TARGET || 'http://127.0.0.1:8787'

  return {
    plugins: [
      vue(),
      // 模板里的 `<el-xxx>` / `v-loading` 编译期逐个 import，替代全量 app.use。
      // importStyle: false —— 样式统一走 shared/plugins/element.ts 的全量 CSS，
      // 见那里的注释；这里若开 css 会按 kebab 猜路径（如 ElTableV2）而构建报错。
      Components({
        dts: false,
        resolvers: [ElementPlusResolver({ importStyle: false })],
      }),
      tailwindcss(),
    ],
    build: {
      rollupOptions: {
        output: { manualChunks: vendorChunk },
      },
    },
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
      css: true,
      server: {
        deps: {
          inline: ['vue-element-plus-x'],
        },
      },
    },
  }
})
