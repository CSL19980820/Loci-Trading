<script setup lang="ts">
import { computed, reactive, watch } from 'vue'

import type { UniversePreset } from '@/shared/types/quant'

const visible = defineModel<boolean>({ default: false })

const props = defineProps<{
  formulaName: string
  presets: UniversePreset[]
  defaultPresetId?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  confirm: [payload: {
    mode: 'single' | 'range'
    tradeDate: string
    start: string
    end: string
    presetId: string
  }]
}>()

const form = reactive({
  mode: 'single' as 'single' | 'range',
  tradeDate: '',
  start: '',
  end: '',
  presetId: '',
})

watch(
  () => [visible.value, props.defaultPresetId] as const,
  ([open]) => {
    if (!open) return
    if (!form.presetId) form.presetId = props.defaultPresetId || props.presets[0]?.id || ''
  },
)

const canConfirm = computed(() => {
  if (form.mode === 'single') return Boolean(form.tradeDate)
  return Boolean(form.start && form.end && form.start <= form.end)
})

function submit(): void {
  if (!canConfirm.value) return
  emit('confirm', {
    mode: form.mode,
    tradeDate: form.tradeDate,
    start: form.start,
    end: form.end,
    presetId: form.presetId,
  })
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="选股范围"
    width="min(32rem, 94vw)"
    append-to-body
    :close-on-click-modal="!busy"
  >
    <p class="select-dialog__hint">
      公式：{{ formulaName || '未命名公式' }} · 试跑已通过
    </p>
    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent="submit">
      <el-form-item label="选股日">
        <el-radio-group v-model="form.mode">
          <el-radio value="single">单日</el-radio>
          <el-radio value="range">区间</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.mode === 'single'" label="日期">
        <el-date-picker
          v-model="form.tradeDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择交易日"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item v-else label="区间">
        <el-date-picker
          v-model="form.start"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="起"
          style="width: 46%"
        />
        <span class="select-dialog__sep">—</span>
        <el-date-picker
          v-model="form.end"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="止"
          style="width: 46%"
        />
      </el-form-item>
      <el-form-item label="股票池">
        <el-select v-model="form.presetId" clearable placeholder="使用草稿默认池" style="width: 100%">
          <el-option
            v-for="item in presets"
            :key="item.id"
            :label="item.label"
            :value="item.id"
          />
        </el-select>
      </el-form-item>
      <p class="select-dialog__note">区间内逐日出信号；结果在下方结果坞展示。</p>
    </el-form>
    <template #footer>
      <el-button :disabled="busy" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="busy" :disabled="!canConfirm" @click="submit">
        开始选股
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.select-dialog__hint {
  margin: 0 0 0.85rem;
  color: var(--muted);
  font-size: 0.84rem;
}

.select-dialog__note {
  margin: 0 0 0 5rem;
  color: var(--mist);
  font-size: 0.78rem;
}

.select-dialog__sep {
  display: inline-block;
  width: 8%;
  text-align: center;
  color: var(--mist);
}
</style>
