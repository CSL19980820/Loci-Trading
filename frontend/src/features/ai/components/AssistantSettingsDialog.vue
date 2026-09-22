<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { Trash2 as Delete, Plus } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { confirmOrThrow } from '@/shared/lib/confirm'
import { vBusy } from '@/shared/directives/busy'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as TabSet } from '@/shared/components/ui/app/TabSet.vue'
import { default as TabPage } from '@/shared/components/ui/app/TabPage.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'


import { computed, onMounted, ref, watch } from 'vue'


import {
  getAiProfile,
  listAiMemories,
  putAiMemoryDocument,
  putAiProfile,
  resetAiProfileDefaults,
} from '@/shared/api/ai_assistant'
import type { AiAssistantProfile } from '@/shared/types/ai_assistant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import {
  MEMORY_QUOTAS,
  groupMemoriesByTarget,
  joinMemoryDocument,
  memoryUsagePct,
} from '../assistantMemoryQuotas'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const tab = ref('instructions')
const loading = ref(false)
const saving = ref(false)
const resetting = ref(false)
const aboutUser = ref('')
const responseStyle = ref('')
const rules = ref<string[]>([])
const newRule = ref('')
const memoryEnabled = ref(true)
const autoMemoryEnabled = ref(true)
const autoMemoryMinTurns = ref(20)
const userDoc = ref('')
const workDoc = ref('')
const usage = ref({ user: 0, memory: 0 })

const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

const userPct = computed(() => memoryUsagePct(userDoc.value.length, MEMORY_QUOTAS.user))
const workPct = computed(() => memoryUsagePct(workDoc.value.length, MEMORY_QUOTAS.memory))

async function load(): Promise<void> {
  loading.value = true
  try {
    const [profile, rows] = await Promise.all([getAiProfile(), listAiMemories()])
    applyProfile(profile)
    const grouped = groupMemoriesByTarget(rows)
    userDoc.value = joinMemoryDocument(grouped.user)
    workDoc.value = joinMemoryDocument(grouped.memory)
    usage.value = profile.memory_usage || {
      user: userDoc.value.length,
      memory: workDoc.value.length,
    }
  } catch (caught) {
    toast.error(toErrorMessage(caught, '加载助手设置失败'))
  } finally {
    loading.value = false
  }
}

function applyProfile(profile: AiAssistantProfile): void {
  aboutUser.value = profile.about_user || ''
  responseStyle.value = profile.response_style || ''
  rules.value = [...(profile.rules || [])]
  memoryEnabled.value = profile.memory_enabled !== false
  autoMemoryEnabled.value = profile.auto_memory_enabled !== false
  autoMemoryMinTurns.value = profile.auto_memory_min_turns || 20
  usage.value = profile.memory_usage || { user: 0, memory: 0 }
}

async function saveProfile(): Promise<void> {
  if (userDoc.value.length > MEMORY_QUOTAS.user) {
    toast.error(`用户画像不得超过 ${MEMORY_QUOTAS.user} 字`)
    return
  }
  if (workDoc.value.length > MEMORY_QUOTAS.memory) {
    toast.error(`工作记忆不得超过 ${MEMORY_QUOTAS.memory} 字`)
    return
  }
  saving.value = true
  try {
    const profile = await putAiProfile({
      about_user: aboutUser.value,
      response_style: responseStyle.value,
      rules: rules.value,
      memory_enabled: memoryEnabled.value,
      auto_memory_enabled: autoMemoryEnabled.value,
      auto_memory_min_turns: autoMemoryMinTurns.value,
    })
    const [userResult, workResult] = await Promise.all([
      putAiMemoryDocument({ target: 'user', content: userDoc.value }),
      putAiMemoryDocument({ target: 'memory', content: workDoc.value }),
    ])
    applyProfile(profile)
    usage.value = {
      user: userResult.usage,
      memory: workResult.usage,
    }
    toast.success('已保存')
  } catch (caught) {
    toast.error(toErrorMessage(caught, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function restoreDefaults(): Promise<void> {
  try {
    await confirmOrThrow({ message: '将恢复产品默认的回答偏好、规则与工作记忆文档；「关于你」会保留。用户画像文档也会恢复为模板。', title: '恢复产品默认', danger: true, confirmText: '恢复', cancelText: '取消' })
  } catch {
    return
  }
  resetting.value = true
  try {
    const profile = await resetAiProfileDefaults()
    applyProfile(profile)
    const rows = await listAiMemories()
    const grouped = groupMemoriesByTarget(rows)
    userDoc.value = joinMemoryDocument(grouped.user)
    workDoc.value = joinMemoryDocument(grouped.memory)
    usage.value = profile.memory_usage || usage.value
    toast.success('已恢复产品默认')
  } catch (caught) {
    toast.error(toErrorMessage(caught, '恢复默认失败'))
  } finally {
    resetting.value = false
  }
}

function addRule(): void {
  const text = newRule.value.trim()
  if (!text) return
  rules.value = [...rules.value, text]
  newRule.value = ''
}

function removeRule(index: number): void {
  rules.value = rules.value.filter((_, current) => current !== index)
}

watch(() => props.open, (open) => { if (open) void load() })
onMounted(() => { if (props.open) void load() })
</script>

<template>
  <DialogPanel
    v-model="visible"
    title="助手设置"
    width="780px"
    align-center
    append-to-body
    :modal="false"
    destroy-on-close
    class="assistant-settings-dialog"
    data-testid="assistant-settings-dialog"
  >
    <FormLayout v-busy="loading" class="assistant-settings" :disabled="loading || saving || resetting" :aria-busy="loading">
      <TabSet v-model="tab" class="assistant-settings__tabs">
        <TabPage label="指令" name="instructions">
          <div class="assistant-settings__split">
            <Label class="assistant-settings__field">
              <span class="assistant-settings__label">关于你</span>
              <TextField
                v-model="aboutUser"
                aria-label="关于你"
                type="textarea"
                :rows="10"
                maxlength="2000"
                show-word-limit
                resize="none"
                placeholder="你是谁、怎么交易、常用策略…（支持 Markdown）"
              />
            </Label>
            <Label class="assistant-settings__field">
              <span class="assistant-settings__label">回答偏好</span>
              <TextField
                v-model="responseStyle"
                aria-label="回答偏好"
                type="textarea"
                :rows="10"
                maxlength="4000"
                show-word-limit
                resize="none"
                placeholder="篇幅、语气、是否先给结论…（支持 Markdown）"
              />
            </Label>
          </div>
        </TabPage>

        <TabPage label="规则" name="rules">
          <div class="assistant-settings__stack">
            <div v-for="(rule, index) in rules" :key="`${index}-${rule}`" class="assistant-settings__line">
              <span>{{ rule }}</span>
              <ActionButton :icon="Delete" icon-only variant="ghost" size="small" :aria-label="`删除第 ${index + 1} 条规则`" @click="removeRule(index)" />
            </div>
            <EmptyState v-if="!rules.length" description="暂无规则" />
            <div class="assistant-settings__composer">
              <TextField v-model="newRule" aria-label="新增规则" placeholder="新增一条硬规则，回车添加" @keyup.enter="addRule" />
              <ActionButton :icon="Plus" @click="addRule">添加</ActionButton>
            </div>
          </div>
        </TabPage>

        <TabPage label="记忆" name="memory">
          <div class="assistant-settings__toolbar">
            <Label class="assistant-settings__chip">
              <span>记忆</span>
              <ToggleSwitch v-model="memoryEnabled" size="small" aria-label="启用记忆" />
            </Label>
            <Label class="assistant-settings__chip">
              <span>满轮整理</span>
              <ToggleSwitch v-model="autoMemoryEnabled" size="small" aria-label="自动整理记忆" :disabled="!memoryEnabled" />
            </Label>
            <Label class="assistant-settings__chip is-grow">
              <span>频率</span>
              <NumberInput
                v-model="autoMemoryMinTurns"
                aria-label="记忆整理间隔"
                :min="5"
                :max="100"
                size="small"
                controls-position="right"
                :disabled="!memoryEnabled || !autoMemoryEnabled"
              />
              <span class="assistant-settings__unit">条</span>
            </Label>
          </div>

          <div class="assistant-settings__docs">
            <Label class="assistant-settings__field">
              <span class="assistant-settings__label">
                用户画像
                <small>{{ userDoc.length }}/{{ MEMORY_QUOTAS.user }}</small>
              </span>
              <span class="assistant-settings__cap-bar" aria-hidden="true"><i :style="{ width: `${userPct}%` }" /></span>
              <TextField
                v-model="userDoc"
                aria-label="用户画像文档"
                type="textarea"
                :rows="12"
                :maxlength="MEMORY_QUOTAS.user"
                resize="vertical"
                :disabled="!memoryEnabled"
                placeholder="一整段 Markdown：角色、偏好、禁忌…"
              />
            </Label>
            <Label class="assistant-settings__field">
              <span class="assistant-settings__label">
                工作记忆
                <small>{{ workDoc.length }}/{{ MEMORY_QUOTAS.memory }}</small>
              </span>
              <span class="assistant-settings__cap-bar" aria-hidden="true"><i :style="{ width: `${workPct}%` }" /></span>
              <TextField
                v-model="workDoc"
                aria-label="工作记忆文档"
                type="textarea"
                :rows="12"
                :maxlength="MEMORY_QUOTAS.memory"
                resize="vertical"
                :disabled="!memoryEnabled"
                placeholder="一整段 Markdown：环境约定、三库、能力边界…"
              />
            </Label>
          </div>
        </TabPage>
      </TabSet>
    </FormLayout>

    <template #footer>
      <ActionButton :busy="resetting" :disabled="loading || saving" @click="restoreDefaults">恢复默认</ActionButton>
      <ActionButton tone="primary" :busy="saving" :disabled="loading || resetting" @click="saveProfile">保存</ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.assistant-settings { min-height: 0; max-height: min(70dvh, 44rem); overflow: auto; overscroll-behavior: contain; scrollbar-width: thin; }
.assistant-settings__tabs :deep(.tab-set__list) { margin: 0 0 var(--gap-3); position: sticky; top: 0; z-index: 1; background: var(--surface); }
.assistant-settings__tabs :deep(.tab-set__list::after) { height: 1px; background: var(--rule); }
.assistant-settings__tabs :deep([data-slot='tabs-trigger']) { height: var(--ctl-h); font-size: var(--ai-fs-body); padding: 0 var(--gap-4); }
.assistant-settings__split, .assistant-settings__docs { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--gap-3); }
.assistant-settings__field { display: flex; flex-direction: column; gap: var(--gap-2); margin: 0; min-width: 0; }
.assistant-settings__field :deep(.text-field__control) { font-size: var(--ai-fs-body); line-height: 1.6; }
.assistant-settings__label { display: flex; align-items: baseline; justify-content: space-between; gap: var(--gap-2); font-size: var(--ai-fs-body); font-weight: 600; color: var(--ink); }
.assistant-settings__label small { font: var(--ai-fs-meta) var(--mono); font-variant-numeric: tabular-nums; color: var(--mist); }
.assistant-settings__cap-bar { display: block; height: var(--gap-1); border-radius: var(--ai-r-pill); background: var(--rule); overflow: hidden; }
.assistant-settings__cap-bar i { display: block; height: 100%; border-radius: inherit; background: var(--seal); }
.assistant-settings__stack { display: flex; flex-direction: column; gap: var(--gap-2); }
.assistant-settings__line { display: flex; align-items: center; gap: var(--gap-2); padding: var(--gap-2); border: 1px solid var(--rule); border-radius: var(--ai-r-chip); background: var(--surface-sunken); }
.assistant-settings__line > span { flex: 1; min-width: 0; font-size: var(--ai-fs-body); line-height: 1.5; overflow-wrap: anywhere; }
.assistant-settings__composer { display: flex; gap: var(--gap-2); padding-top: var(--gap-2); }
.assistant-settings__composer :deep(.text-field) { min-width: 0; }
.assistant-settings__toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-2) var(--gap-3); margin-bottom: var(--gap-3); padding: var(--gap-2); border: 1px solid var(--rule); border-radius: var(--ai-r-card); background: var(--surface-sunken); }
.assistant-settings__chip { display: inline-flex; align-items: center; gap: var(--gap-2); margin: 0; font-size: var(--ai-fs-body); color: var(--ink); white-space: nowrap; }
.assistant-settings__chip.is-grow { margin-left: auto; }
.assistant-settings__chip :deep(.number-input) { width: calc(var(--ctl-h) * 3); }
.assistant-settings__unit { color: var(--mist); font-size: var(--ai-fs-aux); }
@media (max-width: 720px) { .assistant-settings__split, .assistant-settings__docs { grid-template-columns: minmax(0, 1fr); } .assistant-settings__chip.is-grow { margin-left: 0; } }
</style>

<style>
.assistant-settings-dialog.dialog-panel { width: min(780px, calc(100vw - var(--gap-4))) !important; max-width: calc(100vw - var(--gap-4)); max-height: 90dvh; display: flex; flex-direction: column; overflow: hidden; padding: 0; }
.assistant-settings-dialog .dialog-panel__header { flex-shrink: 0; padding: var(--gap-3); border-bottom: 1px solid var(--rule); background: var(--surface-raised); }
.assistant-settings-dialog .dialog-panel__body { display: flex; min-height: 0; flex-direction: column; overflow: hidden; padding: var(--gap-3); }
.assistant-settings-dialog .dialog-panel__footer { flex-shrink: 0; padding: var(--gap-3); border-top: 1px solid var(--rule); background: var(--surface); }
</style>
