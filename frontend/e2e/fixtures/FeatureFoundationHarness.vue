<script setup lang="ts">
import { reactive, ref } from 'vue'
import AssistantPanel from '../../src/features/ai/components/AssistantPanel.vue'
import { Dialog, DialogContent, DialogTitle } from '../../src/shared/components/ui/dialog'
import { Button } from '../../src/shared/components/ui/button'
import { TooltipProvider } from '../../src/shared/components/ui/tooltip'
import ResearchEvidencePanel from '../../src/features/research/components/ResearchEvidencePanel.vue'
import ResearchTemporalDataPanel from '../../src/features/research/components/ResearchTemporalDataPanel.vue'
import AssistantConfirmCard from '../../src/features/ai/components/AssistantConfirmCard.vue'
import ScreenSkillLogicPanel from '../../src/features/strategy/components/ScreenSkillLogicPanel.vue'
import StrategyConverterView from '../../src/features/strategy/StrategyConverterView.vue'
import { createEmptyScreenSkillDraft } from '../../src/features/strategy/composables/screenSkillDraft'
import type { ResearchProfile } from '../../src/shared/types/quant-research'
const view = new URLSearchParams(location.search).get('view') || 'research'
const draft = reactive(createEmptyScreenSkillDraft())
draft.factorsText = 'MA, VOL'
draft.logic[0]!.citationsText = 'ref-a, ref-b'
const replies = ref<string[]>([])
const assistantOpen = ref(false)
const settingsOpen = ref(false)
const commands = ref<string[]>([])
const sends = ref<unknown[]>([])
const messages = ref([{id: 'a1', role: 'assistant' as const, status: 'done' as const, content: '模拟对话内容。'}])
const ask = { prompt: '确认本次研究范围', risk: '仅模拟验收', questions: [
  { id: 'scope', prompt: '选择市场', options: ['A股', '港股'] },
  { id: 'reason', prompt: '补充说明', allow_free_text: true },
] }
const profile = { dimensions: [], market_snapshot: { market_revision: 'fixture-20260922' }, quality: { blocked: false, findings: [{ severity: 'warning', code: 'fixture', message: '模拟数据尚未补全', suggested_fix: '补齐证据' }], market_health: { pit_degraded: false }, market_revision: 'fixture-20260922' } } as unknown as ResearchProfile
Object.assign(window, { __featureFoundation: { draft, replies, assistantOpen, settingsOpen, messages, commands, sends } })
</script>
<template>
  <TooltipProvider>
    <main class="feature-harness" :class="{ 'feature-harness--workbench': view === 'workbench' }">
      <template v-if="view === 'assistant'">
        <Button data-testid="open-assistant" @click="assistantOpen = true">打开助手</Button>
        <Button data-testid="outside-control">外部控件</Button>
        <AssistantPanel :open="assistantOpen" :sessions="[]" :archived-sessions="[]" rail-tab="active" :messages="messages" :agents="[]" :provider-ready="true" :providers="[]" provider="fixture" model="fixture" thinking="off" @close="assistantOpen = false" @settings="settingsOpen = true" @slash-command="commands.push($event)" @send="sends.push($event)" />
        <Dialog v-model:open="settingsOpen"><DialogContent><DialogTitle>测试子设置</DialogTitle><Button @click="settingsOpen = false">完成设置</Button></DialogContent></Dialog>
      </template>
      <StrategyConverterView v-else-if="view === 'workbench'" />
      <template v-else-if="view === 'research'"><ResearchEvidencePanel :profile="profile" :run="null" /><ResearchTemporalDataPanel /></template>
      <AssistantConfirmCard v-else-if="view === 'confirm'" :ask="ask" @reply="replies.push($event)" />
      <ScreenSkillLogicPanel v-else-if="view === 'tags'" :draft="draft" />
    </main>
  </TooltipProvider>
</template>
<style scoped>
.feature-harness { max-width: 1200px; padding: 20px; margin: auto; display: flex; flex-direction: column; gap: 20px; }
.feature-harness--workbench { height: 100dvh; max-width: none; padding: 12px; }
@media (max-width: 640px) { .feature-harness { padding: 10px; } }
</style>
