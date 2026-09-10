import type { App } from 'vue'
import { provideGlobalConfig } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
// CSS 走全量，这是量过的结论，不要再改回按需（2026-09，EP 2.14.3 实测）：
// 打开 ElementPlusResolver 的 `importStyle: 'css'` 后，首屏同步 CSS 从
// 431.36 KB raw / 63.19 KB gz 降到 387.05 KB / 57.07 KB——只省 44.31 KB raw /
// 6.12 KB gz，占首屏总量（354.79 KB gz）的 1.7%。
//
// 代价是要手工维护一张补充清单，且清单不止命令式入口。EP 的
// `es/components/*/style/css` 会带上自身依赖的样式，所以模板里出现过的组件
// 都没问题；漏的是**从不作为模板标签出现**的两类：
//   1. 命令式入口：ElMessage / ElMessageBox / ElNotification / ElLoading；
//   2. 第三方渲染的 EP 组件——`vue-element-plus-x` 从 `element-plus/es` 直接
//      取组件，绕过编译期解析，用到 el-image / el-image-viewer / el-timeline /
//      el-timeline-item / el-upload 这 5 个本仓模板从未写过的组件。
// 只补第 1 类时用 Chromium 实测过：`.el-timeline-item__node` 的 position 从
// absolute 退化成 static，`.el-upload-dragger` 边框归零，
// `.el-image-viewer__canvas` 高度塌成 0——即助手面板整片错版且无任何报错。
// 6 KB gz 换一张跟着第三方库内部实现走的清单，不划算。
import 'element-plus/dist/index.css'

/**
 * Element Plus 全局配置。
 *
 * 这里刻意**不**再 `app.use(ElementPlus)`：全量安装会把 EP 全部 90+ 个组件
 * 钉进首屏 entry chunk（本仓实际只用到 55 个）。组件与指令（`v-loading`）
 * 改由 `vite.config.ts` 的 unplugin-vue-components + ElementPlusResolver
 * 在模板编译期逐个 import——所以模板里照常写 `<el-button>`，无需手动 import。
 *
 * `provideGlobalConfig(..., app, true)` 正是 `app.use(ElementPlus, options)`
 * 内部做的另一半（见 element-plus `make-installer`），locale / size 因此不变。
 * 弹窗默认 top 见 style.css（`--el-dialog-margin-top: 5vh`）。
 */
export function setupElement(app: App): void {
  // size='small' 是密度提升最省力的一刀：全站控件从 32px 降到 EP small 档，
  // 高度再由 CSS 的 --el-component-size-small 钉到 --ctl-h(28px)（见 style.base.css）。
  provideGlobalConfig({ locale: zhCn, size: 'small' }, app, true)
}
