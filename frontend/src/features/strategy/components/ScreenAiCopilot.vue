<script setup lang="ts">
import { MagicStick } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

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
  }>(),
  { busy: false },
)

const emit = defineEmits<{
  'update:instruction': [value: string]
  'update:provider': [value: string]
  'update:model': [value: string]
  'update:thinking': [value: string]
  generate: []
}>()

const canGenerate = computed(() => Boolean(props.instruction.trim() && props.provider && props.referencesReady))
const referenceLabel = computed(() => (props.referencesReady ? '来源已完整' : '待补来源'))
const settingsOpen = ref<string[]>([])
</script>

<template>
  <section class="copilot" aria-label="AI 策略助手">
    <div class="copilot__head">
      <div>
        <span class="copilot__eyebrow">当前草稿助手</span>
        <strong>生成或修改中文策略脉络</strong>
      </div>
      <el-tag size="small" :type="referencesReady ? 'success' : 'warning'" effect="plain">{{ referenceLabel }}</el-tag>
    </div>

    <el-input
      :model-value="instruction"
      type="textarea"
      :rows="4"
      maxlength="1200"
      show-word-limit
      placeholder="描述要新增、删改或核对的策略逻辑；AI 会作用于当前草稿。"
      aria-label="给 AI 的当前草稿修改指令"
      @update:model-value="emit('update:instruction', String($event))"
    />

    <el-collapse v-model="settingsOpen" class="copilot__settings">
      <el-collapse-item title="模型设置" name="settings">
        <div class="copilot__fields">
          <el-select :model-value="provider" placeholder="选择供应商" aria-label="AI 供应商" @update:model-value="emit('update:provider', String($event || ''))">
            <el-option v-for="item in providers" :key="item.name" :label="item.is_default ? `${item.name}（默认）` : item.name" :value="item.name" />
          </el-select>
          <el-select :model-value="model" clearable filterable allow-create placeholder="供应商默认模型" aria-label="AI 模型" @update:model-value="emit('update:model', String($event || ''))">
            <el-option v-for="item in providerModels" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select :model-value="thinking" clearable placeholder="思考程度" aria-label="思考程度" @update:model-value="emit('update:thinking', String($event || ''))">
            <el-option v-for="item in THINKING_OPTIONS" :key="item.value || 'off'" :label="item.label" :value="item.value" />
          </el-select>
        </div>
      </el-collapse-item>
    </el-collapse>

    <div class="copilot__foot">
      <span v-if="!referencesReady">补齐资料来源后才能生成可追溯草稿。</span>
      <span v-else>生成结果需要逐条核对后再保存。</span>
      <el-button type="primary" :icon="MagicStick" :loading="busy" :disabled="!canGenerate" @click="emit('generate')">应用 AI 建议</el-button>
    </div>
  </section>
</template>

<style scoped>
.copilot { display: flex; flex-direction: column; gap: .6rem; min-width: 0; }
.copilot__head, .copilot__foot { display: flex; align-items: flex-start; justify-content: space-between; gap: .65rem; }
.copilot__head strong { display: block; font-size: .92rem; }
.copilot__eyebrow { color: var(--mist); font: .72rem/1.25 var(--mono); }
.copilot__settings :deep(.el-collapse-item__header) { height: 2rem; color: var(--muted); font-size: .8rem; }
.copilot__settings :deep(.el-collapse-item__wrap) { border-bottom: 0; }
.copilot__fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .45rem; padding: .4rem 0; }
.copilot__foot { align-items: center; color: var(--mist); font-size: .78rem; }
@media (max-width: 640px) { .copilot__fields { grid-template-columns: 1fr; } .copilot__foot { align-items: flex-start; flex-direction: column; } }
</style>
