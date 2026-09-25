import { createApp, h, ref } from 'vue'
import { TooltipProvider } from '../../src/shared/components/ui/tooltip'
import AssistantTurnTimeline from '../../src/features/ai/components/AssistantTurnTimeline.vue'
import { renderAssistantMarkdown } from '../../src/features/ai/assistantMarkdown'
import '../../src/style.css'
const message = ref({ id: 'markdown-fixture', role: 'assistant', status: 'streaming', content: '' })
Object.assign(window, { __markdownAudit: { message, render: renderAssistantMarkdown } })
createApp({ render: () => h(TooltipProvider, null, { default: () => h(AssistantTurnTimeline, { message: message.value }) }) }).mount('#app')
