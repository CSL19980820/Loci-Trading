<script setup lang="ts">
import { computed } from 'vue'

import { Button } from '@/shared/components/ui/button'
import DateField from '@/shared/components/ui/app/DateField.vue'

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
    <DateField
      :model-value="model"
      type="daterange"
      value-format="YYYY-MM-DD"
      aria-label="交易日区间"
      class="date-range__picker"
      @update:model-value="onRangeChange"
    />
    <div class="date-range__presets" role="group" aria-label="快捷区间">
      <Button access="read"
        v-for="item in TRADE_DATE_PRESETS"
        :key="item.id"
        size="sm"
        :variant="activePreset === item.id ? 'default' : 'outline'"
        @click="applyPreset(item.id)"
      >
        {{ item.label }}
      </Button>
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
  flex: 0 1 auto;
  width: max-content;
  max-width: 100%;
}

.date-range__picker {
  flex: 0 0 auto;
  width: 18rem;
  min-width: 0;
  max-width: 100%;
}

.date-range__presets {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}

.date-range__hint {
  color: var(--warn);
  font-size: var(--fs-kicker);
}
@media (max-width: 640px) {
  .date-range { width: 100%; }
  .date-range__picker { width:100%; }
  .date-range__presets { width:100%; display:flex; flex-wrap:nowrap; gap:4px; }
  .date-range__presets > button { flex:1 1 0%; padding-inline:4px; font-size:11px; min-width:0; }
}
</style>
