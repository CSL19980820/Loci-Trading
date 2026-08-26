<script setup lang="ts">
import { MagicStick } from '@element-plus/icons-vue'
import { computed } from 'vue'

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
</script>

<template>
  <section class="copilot" :class="{ 'copilot--compact': compact }" aria-label="AI 策略助手">
    <div class="copilot__head">
      <strong>{{ compact ? '改公式' : '生成或修改中文策略脉络' }}</strong>
      <el-tag
        v-if="!compact"
        size="small"
        :type="referencesReady ? 'success' : 'warning'"
        effect="plain"
      >
        {{ referencesReady ? '来源已完整' : '待补来源' }}
      </el-tag>
    </div>

    <el-input
      :model-value="instruction"
      type="textarea"
      :rows="compact ? 5 : 4"
      maxlength="1200"
      show-word-limit
      placeholder="用中文描述要改的逻辑…"
      aria-label="给 AI 的当前草稿修改指令"
      @update:model-value="emit('update:instruction', String($event))"
    />

    <div v-if="!compact" class="copilot__fields">
      <el-select
        :model-value="provider"
        placeholder="选择供应商"
        aria-label="AI 供应商"
        @update:model-value="emit('update:provider', String($event || ''))"
      >
        <el-option
          v-for="item in providers"
          :key="item.name"
          :label="item.is_default ? `${item.name}（默认）` : item.name"
          :value="item.name"
        />
      </el-select>
      <el-select
        :model-value="model"
        clearable
        filterable
        allow-create
        placeholder="供应商默认模型"
        aria-label="AI 模型"
        @update:model-value="emit('update:model', String($event || ''))"
      >
        <el-option
          v-for="item in providerModels"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
      <el-select
        :model-value="thinking"
        clearable
        placeholder="思考程度"
        aria-label="思考程度"
        @update:model-value="emit('update:thinking', String($event || ''))"
      >
        <el-option
          v-for="item in THINKING_OPTIONS"
          :key="item.value || 'off'"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
    </div>

    <div class="copilot__foot">
      <el-button
        type="primary"
        :icon="MagicStick"
        :loading="busy"
        :disabled="!canGenerate"
        @click="emit('generate')"
      >
        {{ compact ? '生成并应用' : '应用 AI 建议' }}
      </el-button>
      <el-button v-if="!referencesReady" text type="primary" @click="emit('manage-references')">
        管理资料来源
      </el-button>
      <el-button v-if="compact" text type="primary" @click="emit('open-assistant')">
        在助手中继续
      </el-button>
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
