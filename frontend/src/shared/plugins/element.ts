import type { App } from 'vue'
import { provideGlobalConfig } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
// CSS 仍走全量：EP 的 css 体积主要在 gzip 后并不大（约 70 KB gz），而按需 CSS
// 一旦漏掉 ElMessage/ElMessageBox/v-loading 这类命令式入口的样式就是线上白板，
// 收益/风险不成比例。JS 侧的按需（真正的大头）由 unplugin-vue-components 负责。
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
  provideGlobalConfig({ locale: zhCn, size: 'default' }, app, true)
}
