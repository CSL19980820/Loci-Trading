<script setup lang="ts">
import { computed } from 'vue'

import CodeEditor from '@/features/ops/components/CodeEditor.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { THINKING_OPTIONS, type LlmModelOption } from '@/shared/lib/llm'
import type { LlmProvider } from '@/shared/types/quant'

import type { ScreenSkillDraftSource } from '../composables/screenSkillDraft'

interface GenerationFormState {
  source: string
  provider: string
  model: string
  thinking: string
}

const props = defineProps<{
  starterSource: ScreenSkillDraftSource
  generationForm: GenerationFormState
  providers: LlmProvider[]
  providerModels: LlmModelOption[]
  busy?: boolean
  referencesReady?: boolean
}>()

const emit = defineEmits<{
  generate: []
}>()

const panelTitle = computed(() => {
  if (props.starterSource === 'description') return 'AI 草稿入口'
  if (props.starterSource === 'tdx') return 'TDX 草稿导入'
  if (props.starterSource === 'ths') return '同花顺草稿导入'
  if (props.starterSource === 'python') return 'Python 草稿导入'
  return '草稿输入'
})

const editorLanguage = computed(() => {
  if (props.starterSource === 'description') return 'markdown'
  if (props.starterSource === 'python') return 'python'
  return 'plaintext'
})

const sourceLabel = computed(() => {
  if (props.starterSource === 'description') return '自然语言策略描述'
  if (props.starterSource === 'tdx') return 'TDX 公式原稿'
  if (props.starterSource === 'ths') return '同花顺公式原稿'
  return 'Python 源码草稿'
})

const sourceHint = computed(() => {
  if (props.starterSource === 'description') {
    return '请写明入选逻辑、数据口径、买卖时点，并先在“资料来源”补充可追溯引用。'
  }
  if (props.starterSource === 'python') {
    return '贴入已有 Python 思路或函数骨架，后续仍可在“代码高级视图”继续细化。'
  }
  return '导入后会归一到当前 Screen Skill 草稿，再做编译与试跑。'
})

const actionLabel = computed(() => {
  if (props.starterSource === 'description') return '生成带来源草稿'
  if (props.starterSource === 'tdx') return '导入 TDX 草稿'
  if (props.starterSource === 'ths') return '导入同花顺草稿'
  return '导入 Python 草稿'
})
</script>

<template>
  <Sheet :title="panelTitle" padded margin>
    <el-alert
      v-if="starterSource === 'description'"
      :type="referencesReady ? 'info' : 'warning'"
      show-icon
      :closable="false"
      class="mb"
      :title="referencesReady ? 'AI 生成会一并带上资料来源。' : '先补资料来源，再发起 AI 草稿生成。'"
    >
      <template #default>
        <span>{{ sourceHint }}</span>
      </template>
    </el-alert>
    <el-form label-position="top" @submit.prevent="emit('generate')">
      <div class="meta-grid">
        <el-form-item label="供应商" :required="starterSource === 'description'">
          <el-select v-model="generationForm.provider" clearable placeholder="选择供应商" class="full">
            <el-option
              v-for="item in providers"
              :key="item.name"
              :label="item.is_default ? `${item.name}（默认）` : item.name"
              :value="item.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型">
          <el-select
            v-model="generationForm.model"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="供应商默认"
            class="full"
          >
            <el-option
              v-for="model in providerModels"
              :key="model.value"
              :label="model.label"
              :value="model.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="思考程度">
          <el-select v-model="generationForm.thinking" clearable class="full">
            <el-option
              v-for="item in THINKING_OPTIONS"
              :key="item.value || 'off'"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item :label="sourceLabel">
        <CodeEditor v-model="generationForm.source" :language="editorLanguage" height="14rem" />
      </el-form-item>
      <div class="sheet-actions-line">
        <el-button
          type="primary"
          :loading="busy"
          :disabled="starterSource === 'description' && !generationForm.provider"
          @click="emit('generate')"
        >
          {{ actionLabel }}
        </el-button>
        <span class="dim">{{ sourceHint }}</span>
      </div>
    </el-form>
  </Sheet>
</template>

<style scoped>
.sheet-actions-line {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.75rem;
}

.full {
  width: 100%;
}

.dim {
  color: var(--mist);
  font-size: 0.82rem;
}

.mb {
  margin-bottom: 0.65rem;
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
