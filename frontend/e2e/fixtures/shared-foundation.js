import { createApp } from 'vue'
import Harness from './SharedFoundationHarness.vue'
import { initTheme } from '../../src/shared/lib/theme'
import '../../src/style.css'
initTheme()
createApp(Harness).mount('#app')
