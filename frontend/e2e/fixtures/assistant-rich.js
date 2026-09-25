import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { PiniaColada } from '@pinia/colada'
import { createRouter, createMemoryHistory } from 'vue-router'
import Harness from './AssistantRichHarness.vue'
import { applyTheme } from '../../src/shared/lib/theme'
import '../../src/style.css'
applyTheme(new URLSearchParams(location.search).get('theme') || 'day', 'seal')
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => h('div') } }] })
await router.push('/')
createApp(Harness).use(createPinia()).use(PiniaColada).use(router).mount('#app')
