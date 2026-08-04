import type { App } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

/** Element Plus 全局注册。弹窗默认 top 见 style.css（`--el-dialog-margin-top: 5vh`）。 */
export function setupElement(app: App): void {
  app.use(ElementPlus, { locale: zhCn, size: 'default' })
}
