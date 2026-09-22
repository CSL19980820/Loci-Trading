<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import type { MarketSyncSettings } from '@/shared/types/quant'
import type { SyncDraft } from '../composables/useSystemSettings'
import { formatNext } from '../composables/opsLabels'

/** 行情同步一节：盘中增量 / 日终重刷 / 并发 三条设置行。 */
const props = defineProps<{
  sync: SyncDraft
  syncMeta: Pick<MarketSyncSettings, 'intraday_job' | 'eod_job'> | null
}>()

const emit = defineEmits<{ recommend: [] }>()

const nextRun = () => {
  const next = props.syncMeta?.eod_job?.next_run_at || props.syncMeta?.intraday_job?.next_run_at
  return next ? formatNext(next) : ''
}
</script>

<template>
  <form class="sys-rows" @submit.prevent>
    <div class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">盘中增量同步</span>
        <p class="settings-row__desc">只在工作日 9–14 点之间按间隔拉取最新行情。</p>
      </div>
      <div class="settings-row__control">
        <Select v-model="sync.interval_minutes" :disabled="!sync.enabled_intraday">
          <SelectTrigger class="interval" aria-label="盘中同步间隔" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="1">每 1 分钟</SelectItem>
            <SelectItem :value="5">每 5 分钟</SelectItem>
            <SelectItem :value="15">每 15 分钟</SelectItem>
            <SelectItem :value="30">每 30 分钟</SelectItem>
          </SelectContent>
        </Select>
        <Switch v-model="sync.enabled_intraday" aria-label="启用盘中增量同步" />
      </div>
    </div>
    <div class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">日终重刷</span>
        <p class="settings-row__desc">
          收盘后整表刷一遍，修正盘中缺口。
          <template v-if="nextRun()">下次 <strong class="next">{{ nextRun() }}</strong></template>
        </p>
      </div>
      <div class="settings-row__control">
        <span class="time-pair">
          <NumberField v-model="sync.eod_hour" class="time-num" :min="12" :max="23" :disabled="!sync.enabled_eod">
            <NumberFieldContent>
              <NumberFieldInput aria-label="日终重刷小时" />
              <NumberFieldIncrement />
              <NumberFieldDecrement />
            </NumberFieldContent>
          </NumberField>
          <span class="time-sep" aria-hidden="true">:</span>
          <NumberField v-model="sync.eod_minute" class="time-num" :min="0" :max="59" :step="5" :disabled="!sync.enabled_eod">
            <NumberFieldContent>
              <NumberFieldInput aria-label="日终重刷分钟" />
              <NumberFieldIncrement />
              <NumberFieldDecrement />
            </NumberFieldContent>
          </NumberField>
        </span>
        <Switch v-model="sync.enabled_eod" aria-label="启用日终重刷" />
      </div>
    </div>
    <div class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">同步并发</span>
        <p class="settings-row__desc">同时拉取的线程数；由服务器执行。</p>
      </div>
      <div class="settings-row__control">
        <NumberField v-model="sync.workers" class="workers-num" :min="1" :max="16">
          <NumberFieldContent>
            <NumberFieldInput aria-label="同步并发数" />
            <NumberFieldIncrement />
            <NumberFieldDecrement />
          </NumberFieldContent>
        </NumberField>
        <Button variant="outline" size="sm" @click="emit('recommend')">推荐配置</Button>
      </div>
    </div>
  </form>
</template>

<style scoped>
.sys-rows {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
}

.interval {
  width: 8.25rem;
}

.time-pair {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
}

.time-num {
  width: 5.5rem;
}

.workers-num {
  width: 6.5rem;
}

.time-sep {
  color: var(--text-tertiary);
  font-family: var(--mono);
}

.next {
  color: var(--text-secondary);
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
