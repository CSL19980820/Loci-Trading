# Loci 前端

Vue 3、TypeScript、Vite、Tailwind CSS 4、Pinia / Colada 与 Vue Router。界面使用仓库内可编辑的 shadcn-vue / Reka UI 源码，表格与虚拟滚动采用 TanStack，图标使用 Lucide，消息反馈使用 Sonner。

业务位于 `src/features/`，共享组件和基础设施位于 `src/shared/`。`components.json` 描述组件生成路径；组件导览见 `docs/ui-component-map.md`，设计建议见 `docs/ui-spec.md`。这些材料是定位与设计参考，不限制模型、架构或界面的后续演进。

## 开发与验证

```sh
bun install
bun run dev
bun run typecheck
bun run test
bun run build
bun run test:e2e
```

按任务选择验证范围。`bun run build` 包含 Vue / TypeScript 类型检查；本地浏览器测试可使用隔离接口夹具，不等同于线上联调或发布验证。

开发代理优先读取 `LOCI_API_TARGET`，其次 `VITE_API_TARGET`，默认指向 `http://127.0.0.1:8787`。版本与锁定信息以 `package.json`、`bun.lock` 为准。

## 组件与性能

组件在使用位置导入；主题、交互、可访问性和业务组合可以直接在源码中改进。全局控件样式位于 `src/style.controls.css`，主题和 Tailwind 语义映射分别位于 `style.theme.css`、`style.tw-theme.css`。

大型图表和编辑器适合按使用场景延迟加载。评估首屏体积时可从新构建的 `dist/index.html` 出发，统计同步脚本、预加载模块及样式；单个异步分片大小不能直接代表首屏下载量。旧报告中的包体与截图仅对应其记录的快照，不作为当前性能结论。

生成目录与临时实验产物可放在已忽略的位置，避免被样式扫描误认为应用源码。具体分包方式以真实测量和使用体验判断，不把现有配置固化为永久规则。

## 当前升级兼容性记录

2026-09-16 的本地升级验证中，TypeScript 7.0.2 无法被当前 `vue-tsc` 正常加载：编译工具读取 `typescript/lib/tsc` 时收到包导出错误。因此暂保留 TypeScript 6.0.3，不关闭类型检查来强行升级。编译工具链兼容后可再次验证升级。
