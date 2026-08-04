import { createApp } from 'vue'
import { PiniaColada } from '@pinia/colada'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './shared/router'
import { setupElement } from './shared/plugins/element'
import { initTheme } from './shared/lib/theme'
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
  // 主窗：挂载后立刻卸，避免「开账·启动中」叠字。
  dismissBootSplash()
  requestAnimationFrame(dismissBootSplash)
}
