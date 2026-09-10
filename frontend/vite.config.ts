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
 * 异步分片里才是对的。同理**不要**给 monaco 建 `vendor-monaco` 组：实测
 * （2026-09）这么做会让首屏同步分片从 1167.32 KB raw / 306.73 KB gz 暴涨到
 * 5302.71 KB / 1376.75 KB——4.5 倍，整包编辑器被拽进首屏。
 * echarts 同理。monaco 现有的 format(2.26 MB) 与
 * wordPartOperations(1.13 MB) 两片也不必合并：它们都只挂在 CodeEditor 的动态
 * import 下，合并省不下字节，只少一个请求，却把缓存粒度做粗。
 *
 * element-plus 只把「CSS + 运行时基座」建组，**组件本体不建组**。理由是
 * 建组会把整包 EP 钉成首屏依赖：entry 只要静态引用一个 EP 模块，整个组就变
 * 同步分片，连只被异步路由用到的组件也一起进首屏。实测（2026-09，EP 2.14.3）
 * 全量建组的首屏同步 JS 为 888.64 KB raw / 291.58 KB gz；改成只建基座组后
 * 降到 735.96 KB / 243.54 KB（-17.2% raw / -16.5% gz），移出去的 167 KB EP
 * 组件散落进了真正用到它们的异步路由分片。代价是 entry 从 97.98 KB 涨到
 * 500.17 KB（首屏用到的 EP 组件与业务代码同 chunk），本应用产物由本机
 * FastAPI 以 immutable 头从磁盘发出，重下代价约等于零，换每次冷启动都少解析
 * 152 KB JS 是划算的。
 *
 * EP 的 dist CSS 必须留在组里：它是 350.99 KB 的巨型且几乎不变的模块，
 * 单独成一个产物才不会被业务样式改动带着失效。
 *
 * 注意 `vue-element-plus-x` 与 `@element-plus/icons-vue` 都不含前置 `/` 的
 * `/element-plus/`，因此不会命中下面任何一条 EP 规则。
 */
function vendorChunk(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined
  const path = id.replace(/\\/g, '/')
  if (/\/element-plus\/(dist|theme-chalk)\//.test(path)) return 'vendor-element-plus'
  if (/\/element-plus\/es\/(utils|hooks|constants|locale)\//.test(path)) return 'vendor-element-plus'
  if (/\/element-plus\/es\/(index|defaults|make-installer)/.test(path)) return 'vendor-element-plus'
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
      // importStyle: false —— 样式统一走 shared/plugins/element.ts 的全量 CSS。
      // 开 'css' 能正常构建（EP 2.14.3 实测，ElTableV2 路径已不再报错），但只省
      // 6.12 KB gz 首屏 CSS，代价是漏掉 vue-element-plus-x 渲染的 5 个 EP 组件
      // 样式；完整实测与结论见 element.ts 的注释。
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
