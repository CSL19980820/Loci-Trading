import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { PiniaColada } from '@pinia/colada'
import { createRouter, createMemoryHistory } from 'vue-router'
import Harness from './FeatureFoundationHarness.vue'
import { initTheme } from '../../src/shared/lib/theme'
import '../../src/style.css'
initTheme()
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => h('div') } }] })
await router.push('/strategy-converter')
createApp(Harness).use(createPinia()).use(PiniaColada).use(router).mount('#app')
