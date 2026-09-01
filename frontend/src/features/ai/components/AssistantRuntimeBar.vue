<script setup lang="ts">
import { computed } from 'vue'

import type { AiProviderProfile } from '@/shared/types/ai_assistant'

const SEP = '\u0000'

export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

const THINKING_OPTIONS: { value: ThinkingLevel; label: string; hint: string }[] = [
  { value: 'off', label: '关闭', hint: '不请求推理' },
  { value: 'low', label: '低', hint: '轻量推理' },
  { value: 'medium', label: '中', hint: '平衡' },
  { value: 'high', label: '高', hint: '更深推理' },
  { value: 'xhigh', label: '极高', hint: '更重推理' },
  { value: 'max', label: '最大', hint: '最深推理' },
]

const props = defineProps<{
  providers: AiProviderProfile[]
  provider: string
  model: string
  thinking: ThinkingLevel
  disabled?: boolean
}>()

const emit = defineEmits<{
  select: [payload: { provider: string; model: string }]
  thinking: [level: ThinkingLevel]
}>()

function encodePair(providerName: string, modelName: string): string {
  return `${providerName}${SEP}${modelName}`
}

function decodePair(value: string): { provider: string; model: string } | null {
  const at = value.indexOf(SEP)
  if (at <= 0) return null
  return { provider: value.slice(0, at), model: value.slice(at + 1) }
}

const modelValue = computed(() => {
  if (!props.provider || !props.model) return ''
  return encodePair(props.provider, props.model)
})

const groups = computed(() =>
  props.providers
    .filter((item) => item.is_active !== false && item.models.length > 0)
    .map((item) => ({
      name: item.name,
      isDefault: item.is_default,
      models: item.models,
    })),
)

const thinkingLabel = computed(
  () => THINKING_OPTIONS.find((item) => item.value === props.thinking)?.label ?? '关闭',
)

function onModelChange(raw: string): void {
  const pair = decodePair(String(raw ?? ''))
  if (!pair) return
  emit('select', pair)
}

function onThinkingChange(raw: string): void {
  const next = String(raw ?? '') as ThinkingLevel
  if (THINKING_OPTIONS.some((item) => item.value === next)) emit('thinking', next)
}
</script>

<template>
  <div class="assistant-runtime" role="group" aria-label="模型与思考">
    <el-select
      class="assistant-runtime__model"
      :model-value="modelValue"
      size="small"
      filterable
      placeholder="选择模型"
      aria-label="选择供应商与模型"
      popper-class="assistant-runtime-popper"
      :disabled="disabled || !groups.length"
      @update:model-value="onModelChange"
    >
      <el-option-group
        v-for="group in groups"
        :key="group.name"
        :label="group.isDefault ? `${group.name} · 默认` : group.name"
      >
        <el-option
          v-for="item in group.models"
          :key="encodePair(group.name, item)"
          :label="item"
          :value="encodePair(group.name, item)"
        >
          <span class="assistant-runtime__option">
            <span class="assistant-runtime__option-model">{{ item }}</span>
            <span class="assistant-runtime__option-provider">{{ group.name }}</span>
          </span>
        </el-option>
      </el-option-group>
    </el-select>

    <div class="assistant-runtime__thinking-wrap">
      <span class="assistant-runtime__thinking-prefix" id="assistant-thinking-label">思考</span>
      <el-select
        class="assistant-runtime__thinking"
        :model-value="thinking"
        size="small"
        aria-labelledby="assistant-thinking-label"
        popper-class="assistant-runtime-popper"
        :disabled="disabled"
        @update:model-value="onThinkingChange"
      >
        <el-option
          v-for="item in THINKING_OPTIONS"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        >
          <span class="assistant-runtime__option">
            <span class="assistant-runtime__option-model">{{ item.label }}</span>
            <span class="assistant-runtime__option-provider">{{ item.hint }}</span>
          </span>
        </el-option>
      </el-select>
    </div>
    <span class="assistant-runtime__sr-only">当前思考：{{ thinkingLabel }}</span>
  </div>
</template>

<style scoped>
.assistant-runtime {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: .4rem;
  min-width: 0;
  flex: 0 1 auto;
}

.assistant-runtime__model {
  width: 11rem;
  flex: 0 1 11rem;
  min-width: 0;
}

.assistant-runtime__thinking-wrap {
  display: inline-flex;
  align-items: center;
  gap: .28rem;
  flex: 0 0 auto;
  min-width: 0;
}

.assistant-runtime__thinking {
  width: 5.25rem;
  flex: 0 0 auto;
}

.assistant-runtime__thinking-prefix {
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  flex: 0 0 auto;
  line-height: 1;
}

/* EP select 默认 box-shadow 当边框；清掉内层 input 再描边，避免双线 */
.assistant-runtime__model :deep(.el-select__wrapper),
.assistant-runtime__thinking :deep(.el-select__wrapper) {
  min-height: var(--ctl-h);
  padding: 0 .55rem;
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card);
  background: color-mix(in srgb, var(--panel-2) 88%, transparent);
  box-shadow: none !important;
}

.assistant-runtime__model :deep(.el-select__wrapper.is-focused),
.assistant-runtime__model :deep(.el-select__wrapper.is-hovering:not(.is-focused)),
.assistant-runtime__thinking :deep(.el-select__wrapper.is-focused),
.assistant-runtime__thinking :deep(.el-select__wrapper.is-hovering:not(.is-focused)) {
  border-color: color-mix(in srgb, var(--seal) 45%, var(--rule));
  box-shadow: none !important;
}

.assistant-runtime__model :deep(.el-select__selection),
.assistant-runtime__thinking :deep(.el-select__selection),
.assistant-runtime__model :deep(.el-select__selected-item),
.assistant-runtime__thinking :deep(.el-select__selected-item),
.assistant-runtime__model :deep(.el-select__input-wrapper),
.assistant-runtime__thinking :deep(.el-select__input-wrapper),
.assistant-runtime__model :deep(.el-select__input),
.assistant-runtime__thinking :deep(.el-select__input) {
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
  background: transparent;
}

.assistant-runtime__model :deep(.el-select__placeholder),
.assistant-runtime__model :deep(.el-select__selected-item) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-runtime__option {
  display: flex;
  width: 100%;
  align-items: baseline;
  justify-content: space-between;
  gap: .75rem;
}

.assistant-runtime__option-model {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 选项被 teleport 到 body；契约块靠 .assistant-runtime-popper 把变量送进去 */
.assistant-runtime__option-provider {
  flex: 0 0 auto;
  color: var(--mist);
  font-size: var(--ai-fs-aux);
}

.assistant-runtime__sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
