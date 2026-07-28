<script setup lang="ts">
import { dialogWidth } from '@/shared/lib/format'
import { THINKING_OPTIONS } from '@/shared/lib/llm'
import type { LlmProvider, StrategyJob } from '@/shared/types/quant'

defineProps<{
  modelValue: boolean
  title: string
  configTarget: string
  busy: boolean
  form: {
    cron: string
    auto_review: boolean
    use_ai_pick: boolean
    provider: string
    model: string
    thinking: string
    trading_days: number
    top_n: number
    hold_days: number
    stop_loss_pct: number
    enabled: boolean
  }
  selectedProviderModels: string[]
  llmProviders: LlmProvider[]
  strategyJobs: Record<string, StrategyJob>
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  save: [slug: string]
  remove: [slug: string]
  closed: []
}>()
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="dialogWidth()"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
    @closed="emit('closed')"
  >
    <el-form label-position="top" @submit.prevent="emit('save', configTarget)">
      <div class="config-grid">
        <el-form-item label="Cron 表达式">
          <el-input v-model.trim="form.cron" placeholder="45 15 * * 1-5（留空=仅手动）" />
        </el-form-item>
        <el-form-item label="每次取前 N 名">
          <el-input-number v-model="form.top_n" :min="0" :max="200" :controls="false" class="full" />
        </el-form-item>
        <el-form-item label="验证交易日数">
          <el-input-number v-model="form.trading_days" :min="1" :max="500" :controls="false" class="full" />
        </el-form-item>
        <el-form-item label="默认持有天数">
          <el-input-number v-model="form.hold_days" :min="1" :max="250" :controls="false" class="full" />
        </el-form-item>
        <el-form-item label="止损 %（负数）">
          <el-input-number v-model="form.stop_loss_pct" :step="0.5" :controls="false" class="full" />
        </el-form-item>
      </div>
      <el-checkbox v-model="form.auto_review">自动复盘（选完写入候选池）</el-checkbox>
      <el-checkbox v-model="form.use_ai_pick">用 AI 从结果里挑前 N</el-checkbox>
      <el-checkbox v-model="form.enabled">启用定时任务</el-checkbox>
      <div v-if="form.use_ai_pick" class="config-grid ai-bind">
        <el-form-item label="LLM 供应商">
          <el-select v-model="form.provider" clearable placeholder="使用全局默认" class="full">
            <el-option label="使用全局默认" value="" />
            <el-option v-for="item in llmProviders" :key="item.id" :label="item.name" :value="item.name">
              <span>{{ item.name }}</span>
              <span v-if="item.is_default" class="dim"> · 默认</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="模型">
          <el-select
            v-model="form.model"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="供应商默认"
            class="full"
          >
            <el-option
              v-for="model in selectedProviderModels"
              :key="model"
              :label="model"
              :value="model"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="思考程度">
          <el-select v-model="form.thinking" class="full">
            <el-option
              v-for="opt in THINKING_OPTIONS"
              :key="opt.value || 'off'"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </div>
      <p v-if="form.use_ai_pick" class="form-hint">
        同一供应商可换模型与思考程度；禁止以满仓为由否决。
      </p>
      <p v-if="strategyJobs[configTarget]?.bound" class="form-hint">
        已绑定：cron {{ strategyJobs[configTarget].cron || '手动' }}，
        自动复盘 {{ strategyJobs[configTarget].config?.record_candidates ? '开' : '关' }}，
        top_n {{ strategyJobs[configTarget].config?.top_n || '不限' }}
      </p>
    </el-form>
    <template #footer>
      <el-button
        v-if="strategyJobs[configTarget]?.bound"
        :disabled="busy"
        @click="emit('remove', configTarget)"
      >
        解除绑定
      </el-button>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :disabled="busy || !configTarget" @click="emit('save', configTarget)">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 0.75rem;
}
.ai-bind {
  margin-top: 0.65rem;
}
.full {
  width: 100%;
}
.dim {
  color: var(--mist);
  font-size: 0.82rem;
}
@media (max-width: 640px) {
  .config-grid {
    grid-template-columns: 1fr;
  }
}
</style>
