<script setup lang="ts">
import { computed } from 'vue'

import {
  TRADE_DATE_PRESETS,
  clampTradeDateRange,
  isValidTradeDateRange,
  presetTradeDateRange,
  type TradeDatePreset,
  type TradeDateRange,
} from '../composables/tradeDateRange'

const model = defineModel<TradeDateRange | null>({ default: null })
const props = defineProps<{
  /** 休市时「今日」落到最近交易日 */
  lastTradingDay?: string | null
}>()

const activePreset = computed<TradeDatePreset | ''>(() => {
  const cur = model.value
  if (!cur) return ''
  for (const item of TRADE_DATE_PRESETS) {
    const preset = presetTradeDateRange(item.id, new Date(), props.lastTradingDay)
    if (preset[0] === cur[0] && preset[1] === cur[1]) return item.id
  }
  return ''
})

function applyPreset(id: TradeDatePreset): void {
  model.value = presetTradeDateRange(id, new Date(), props.lastTradingDay)
}

function onRangeChange(value: TradeDateRange | null): void {
  if (!value) {
    model.value = null
    return
  }
  const next = clampTradeDateRange(value)
  model.value = next
}

const invalid = computed(() => {
  const cur = model.value
  if (!cur) return false
  return !isValidTradeDateRange(cur)
})
</script>

<template>
  <div class="date-range" aria-label="交易日区间">
    <el-date-picker
      :model-value="model"
      type="daterange"
      value-format="YYYY-MM-DD"
      start-placeholder="起"
      end-placeholder="止"
      unlink-panels
      clearable
      size="small"
      class="date-range__picker"
      @update:model-value="onRangeChange(($event as TradeDateRange | null) ?? null)"
    />
    <div class="date-range__presets" role="group" aria-label="快捷区间">
      <el-button
        v-for="item in TRADE_DATE_PRESETS"
        :key="item.id"
        size="small"
        round
        :type="activePreset === item.id ? 'primary' : 'default'"
        :plain="activePreset !== item.id"
        @click="applyPreset(item.id)"
      >
        {{ item.label }}
      </el-button>
    </div>
    <span v-if="invalid" class="date-range__hint">跨度最多一个月</span>
  </div>
</template>

<style scoped>
.date-range {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.45rem;
  min-width: 0;
}

.date-range__picker {
  width: 15.5rem;
}

.date-range__presets {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}

.date-range__presets :deep(.el-button) {
  margin: 0;
  padding: 0.2rem 0.55rem;
  height: 1.7rem;
}

.date-range__hint {
  color: var(--loss);
  font-size: 0.72rem;
}
</style>
