import { createApp } from 'vue'
import { PiniaColada } from '@pinia/colada'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './shared/router'
import { setupElement } from './shared/plugins/element'
import { initTheme } from './shared/lib/theme'
// EP 深色变量：夜间/墨黑外观靠 html.dark 生效，否则表格边框、分页、下拉会漏浅色
import 'element-plus/theme-chalk/dark/css-vars.css'
import './style.css'

initTheme()

const isPeekWindow = location.pathname.startsWith('/peek')

const app = createApp(App)
setupElement(app)
const pinia = createPinia()
app.use(pinia)
app.use(PiniaColada)
app.use(router)
app.mount('#app')

function dismissBootSplash(): void {
  const splash = document.getElementById('boot-splash')
  if (!splash) return
  const api = (
    window as Window & {
      __lociBootSplash?: { complete?: (done: () => void) => void }
    }
  ).__lociBootSplash
  if (api?.complete) {
    api.complete(() => splash.remove())
    return
  }
  splash.remove()
}

if (isPeekWindow) {
  // 行情小窗：钉死 /peek，避免 WebView 二次窗偶发落到主壳（底栏+「开账·启动中」）。
  void router.isReady().then(async () => {
    if (router.currentRoute.value.name !== 'peek') {
      await router.replace({ name: 'peek' })
    }
    dismissBootSplash()
  })
  window.setTimeout(dismissBootSplash, 2500)
} else {
  // 浏览器模式在此拉满；桌面原生页已完成时，SPA 标记会在模块执行前移除占位。
  dismissBootSplash()
}
