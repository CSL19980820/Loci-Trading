import { createApp, h } from 'vue'
import ConfirmHost from '../../src/shared/components/dialogs/ConfirmHost.vue'
import GuardianConsultPanel from '../../src/features/ops/components/GuardianConsultPanel.vue'
import { TooltipProvider } from '../../src/shared/components/ui/tooltip'
import { initTheme } from '../../src/shared/lib/theme'
import '../../src/style.css'
initTheme()
const model = new URLSearchParams(location.search).get('model') ?? 'fixture-model'
createApp({ render: () => h(TooltipProvider, null, { default: () => h('div', { style: 'height:100dvh;display:flex;min-width:0;width:100%;max-width:1280px;margin:auto' }, [h(GuardianConsultPanel, { model }), h(ConfirmHost)]) }) }).mount('#app')
