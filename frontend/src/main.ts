import { createApp } from 'vue'
import { PiniaColada } from '@pinia/colada'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './shared/router'
import { setupElement } from './shared/plugins/element'
import { initTheme } from './shared/lib/theme'
import './style.css'

initTheme()

const app = createApp(App)
setupElement(app)
const pinia = createPinia()
app.use(pinia)
app.use(PiniaColada)
app.use(router)
app.mount('#app')

requestAnimationFrame(() => {
  const splash = document.getElementById('boot-splash')
  if (!splash) return
  splash.classList.add('is-hide')
  window.setTimeout(() => splash.remove(), 280)
})
