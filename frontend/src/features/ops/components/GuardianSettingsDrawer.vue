<script setup lang="ts">
import { confirmOrThrow } from '@/shared/lib/confirm'
import { default as SidePanel } from '@/shared/components/ui/app/SidePanel.vue'
import { Notice } from '@/shared/components/ui/app/presentation'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import PhasePromptEditor from '@/shared/components/PhasePromptEditor.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'

import { computed, ref, watch } from 'vue'

import type { GuardianConfig } from '@/shared/types/guardian'
import type { LlmProvider } from '@/shared/types/quant'
const open = defineModel<boolean>({ default: false })
const props = defineProps<{ config: GuardianConfig; defaultPrompt: string; defaultWeeklyPrompt?: string; providers: LlmProvider[]; providersLoading?: boolean; busy: boolean; error: string; startOnSave: boolean }>()
const emit = defineEmits<{ save: [config: GuardianConfig] }>()
const draft = ref<GuardianConfig>({ ...props.config })
const baseline = ref('')
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
const models = computed(() => props.providers.find(p => p.name === draft.value.provider)?.models ?? [])
watch(open, value => {
  if (!value) return
  draft.value = JSON.parse(JSON.stringify(props.config))
  baseline.value = JSON.stringify(draft.value)
  if (props.startOnSave) draft.value.enabled = true
})
async function close(done: () => void) {
  if (dirty.value) {
    try { await confirmOrThrow({ message: '关闭后将丢失未保存的交易员配置。', title: '放弃修改', confirmText: '放弃修改', cancelText: '继续编辑' }) }
    catch { return }
  }
  done()
}
defineExpose({ isDirty: () => open.value && dirty.value })
</script>
<template>
  <SidePanel v-model="open" class="guardian-settings-drawer" title="交易员设置" size="min(560px, 100vw)" :before-close="close" :close-on-click-modal="false">
    <Notice v-if="error" :title="error" tone="error" :closable="false" show-icon />
    <FormLayout label-position="top" @submit.prevent>
      <div class="settings-section-title"><span>01</span><h3>选择模型</h3></div>
      <FormField label="模型供应商"><ChoiceField v-model="draft.provider" :busy="providersLoading" :disabled="providersLoading" placeholder="选择已配置的供应商" @change="draft.model = ''"><ChoiceOption v-for="p in providers" :key="p.id" :label="p.name" :value="p.name" /></ChoiceField></FormField>
      <FormField label="守护模型"><ChoiceField v-model="draft.model" :busy="providersLoading" :disabled="providersLoading" filterable placeholder="选择模型"><ChoiceOption v-for="m in models" :key="m" :label="m" :value="m" /></ChoiceField></FormField>
      <div class="settings-section-title"><span>02</span><h3>分时段提示词</h3></div>
      <PhasePromptEditor v-model:common-prompt="draft.common_prompt" v-model:prompt="draft.prompt" v-model:premarket-prompt="draft.premarket_prompt" v-model:review-prompt="draft.review_prompt" v-model:weekly-prompt="draft.weekly_prompt" :default-prompt="defaultPrompt" :default-weekly-prompt="defaultWeeklyPrompt" separate-weekly />
      <div class="settings-section-title"><span>03</span><h3>运行与通知</h3></div>
      <FormField label="启动交易员"><ToggleSwitch v-model="draft.enabled" active-text="交易时段每 5 分钟运行" aria-label="启动交易员" /></FormField>
      <FormField label="合并推送"><ToggleSwitch v-model="draft.notify" active-text="使用已配置的通知通道" /></FormField>
    </FormLayout>
    <template #footer><div class="settings-footer"><span>{{ dirty ? '有未保存的修改' : '配置已同步' }}</span><ActionButton access="read" :disabled="busy" @click="open = false">取消</ActionButton><ActionButton tone="primary" :busy="busy" :disabled="providersLoading" @click="emit('save', draft)">保存配置</ActionButton></div></template>
  </SidePanel>
</template>
<style scoped>
.settings-section-title { display: flex; align-items: center; gap: var(--gap-2); margin: var(--gap-4) 0 var(--gap-3); }
.settings-section-title > span { font: var(--fs-aux) var(--mono); color: var(--mist); }
.settings-section-title h3 { margin: 0; font-size: var(--fs-body); font-weight: 600; }
.settings-section-title .action-button { margin-left: auto; }
.settings-footer { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-2); }
.settings-footer > span { margin-right: auto; color: var(--muted); font-size: var(--fs-aux); }
.settings-section-title { padding-bottom: var(--gap-2); border-bottom: 1px solid var(--rule); }
.settings-section-title > span { color: var(--seal-ink); background: var(--seal-soft); padding: var(--gap-1) var(--gap-2); border-radius: var(--radius-sm); }
.guardian-settings-drawer :deep(.side-panel__body) { overscroll-behavior: contain; }
.guardian-settings-drawer :deep(.side-panel__footer) { border-top: 1px solid var(--rule); background: var(--surface-sunken); }
@media(max-width:480px) { .settings-footer > span { width:100%; } }
</style>
