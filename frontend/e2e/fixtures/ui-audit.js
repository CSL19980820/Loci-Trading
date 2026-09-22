import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { PiniaColada } from '@pinia/colada'
import { createRouter, createMemoryHistory } from 'vue-router'
import { initTheme } from '../../src/shared/lib/theme'
import Harness from './UiAuditHarness.vue'
import '../../src/style.css'
initTheme()
const router = createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:() => h('div')}}]})
const app = createApp(Harness).use(createPinia()).use(PiniaColada).use(router)
app.directive('busy', {mounted() {},updated() {}})
await router.push('/')
app.mount('#app')
