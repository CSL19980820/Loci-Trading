# Frontend (Loci UI)

Vue3 + Pinia + Element Plus。按限界上下文分 features，共享壳在 shared。

开发: `bun install && bun run dev`
构建: `bun run build`

## 产物分包

`vite.config.ts` 的 `vendorChunk` 决定首屏同步分片。当前（2026-09）首屏同步
总量 **1167.32 KB raw / 306.73 KB gz**（JS 735.96 / 243.54，CSS 431.36 / 63.19），
monaco、echarts、助手 UI 全部在异步分片里。

改分包前先量：`bunx vite build` 后读 `dist/index.html` 里的 `<script>` +
`modulepreload` + `stylesheet`，那一组才是首屏同步集合，`vite build` 打印的分片
清单里最大的几项（format 2.26 MB、wordPartOperations 1.13 MB）都是异步的。

三条不要踩的坑，都有实测：

- 给 monaco 或 echarts 建 `vendor-*` 组 → 首屏同步涨到 5302.71 KB / 1376.75 KB。
- 把 element-plus 整包建组 → 首屏同步 JS 从 735.96 KB 涨回 888.64 KB。
- 把 EP 样式改成按需（`importStyle: 'css'`）→ 只省 6.12 KB gz，却丢掉
  `vue-element-plus-x` 渲染的 el-image / el-image-viewer / el-timeline /
  el-timeline-item / el-upload 五个组件的样式。详见 `src/shared/plugins/element.ts`。

`dist-*` 只有 `dist/` 和 `dist-rolldown/` 在 .gitignore 里；用别的 `--outDir`
做实验会被 Tailwind 当成源码扫描，凭空给 index.css 加进几 KB 工具类，量出来的
数字就不可比了。实验完记得删。
