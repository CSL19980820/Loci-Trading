<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed } from 'vue'
import { Sparkles } from '@lucide/vue'

import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Textarea } from '@/shared/components/ui/textarea'
import { THINKING_OPTIONS, type LlmModelOption } from '@/shared/lib/llm'
import type { LlmProvider } from '@/shared/types/quant'

const props = withDefaults(
  defineProps<{
    instruction: string
    provider: string
    model: string
    thinking: string
    providers: LlmProvider[]
    providerModels: LlmModelOption[]
    referencesReady: boolean
    busy?: boolean
    compact?: boolean
  }>(),
  { busy: false, compact: false },
)

const emit = defineEmits<{
  'update:instruction': [value: string]
  'update:provider': [value: string]
  'update:model': [value: string]
  'update:thinking': [value: string]
  generate: []
  'open-assistant': []
  'manage-references': []
}>()

const canGenerate = computed(() => Boolean(props.instruction.trim() && props.provider && props.referencesReady))

/** 「不启思考」的空串在 Select 里是一个合法选项值会与「未选择」撞车，用 off 哨兵代一层。 */
const thinkingModel = computed({
  get: () => props.thinking || 'off',
  set: (value: string) => emit('update:thinking', value === 'off' ? '' : value),
})

/**
 * 模型既要能选（目录里启用的），也要能自己写（目录没登记的新模型），
 * shadcn 的 `Select` 只有固定选项，所以这里用原生 `datalist` 承载「可搜 + 可造」。
 */
const modelListId = 'screen-ai-copilot-models'
</script>

<template>
  <section class="flex h-full min-w-0 flex-col gap-2" :class="{ 'gap-1.5': compact }" aria-label="AI 策略助手">
    <!--
      compact（策稿台侧栏）里不再印「改公式」：外层侧栏头上已经写着「助手」，
      两行说的是同一件事。这一行现在只留真正有信息量的来源状态 tag —— 它决定
      能不能点「生成」，以前反而只在 compact 里被藏掉了。
    -->
    <div class="flex items-start justify-between gap-2">
      <strong v-if="!compact" class="text-title font-bold">生成或修改中文策略脉络</strong>
      <UiBadge :variant="referencesReady ? 'ok' : 'warn'">
        {{ referencesReady ? '来源已完整' : '待补来源' }}
      </UiBadge>
    </div>

    <div class="copilot__instruction">
      <Textarea
        :model-value="instruction"
        :rows="compact ? 5 : 4"
        maxlength="1200"
        placeholder="用中文描述要改的逻辑…"
        aria-label="给 AI 的当前草稿修改指令"
        @update:model-value="(value) => emit('update:instruction', String(value))"
      />
      <span class="copilot__count">{{ instruction.length }}/1200</span>
    </div>

    <div v-if="!compact" class="copilot__fields">
      <Select :model-value="provider" @update:model-value="(value) => emit('update:provider', String(value || ''))">
        <SelectTrigger class="w-full" aria-label="AI 供应商">
          <SelectValue placeholder="选择供应商" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem
            v-for="item in providers"
            :key="item.name"
            :value="item.name"
          >
            {{ item.is_default ? `${item.name}（默认）` : item.name }}
          </SelectItem>
        </SelectContent>
      </Select>
      <Input
        :model-value="model"
        :list="modelListId"
        placeholder="供应商默认模型"
        aria-label="AI 模型"
        @update:model-value="(value) => emit('update:model', String(value || ''))"
      />
      <datalist :id="modelListId">
        <option v-for="item in providerModels" :key="item.value" :value="item.value">
          {{ item.label }}
        </option>
      </datalist>
      <Select v-model="thinkingModel">
        <SelectTrigger class="w-full" aria-label="思考程度">
          <SelectValue placeholder="思考程度" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem
            v-for="item in THINKING_OPTIONS"
            :key="item.value || 'off'"
            :value="item.value || 'off'"
          >
            {{ item.label }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>

    <div class="copilot__foot">
      <Button
        :disabled="!canGenerate || busy"
        @click="emit('generate')"
      >
        <Spinner v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
        <Sparkles v-else />
        {{ compact ? '生成并应用' : '应用 AI 建议' }}
      </Button>
      <Button v-if="!referencesReady" variant="link" @click="emit('manage-references')">
        管理资料来源
      </Button>
      <Button v-if="compact" variant="link" @click="emit('open-assistant')">
        在助手中继续
      </Button>
    </div>
    <p v-if="compact && !referencesReady" class="copilot__tip">补齐资料来源后才能生成。</p>
  </section>
</template>

<style scoped>
.copilot {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-width: 0;
  height: 100%;
}

.copilot__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.65rem;
}

.copilot__head strong {
  font-size: 0.92rem;
}

.copilot__instruction {
  position: relative;
  min-width: 0;
}

.copilot__count {
  position: absolute;
  right: 0.45rem;
  bottom: 0.25rem;
  color: var(--mist);
  font: var(--fs-micro) / 1 var(--mono);
}

.copilot__fields {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.4rem;
}

.copilot__foot {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}

.copilot__tip {
  margin: 0;
  color: var(--mist);
  font-size: 0.76rem;
}

.copilot--compact .copilot__foot {
  flex-direction: column;
  align-items: stretch;
}
</style>
