<script setup lang="ts">
import { reactive } from 'vue'

import { getMarketSyncSettings, saveMarketSyncSettings } from '@/shared/api/quant'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { MarketSyncSettings } from '@/shared/types/quant'
import { formatNext } from '../composables/opsLabels'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{
  'jobs-changed': []
}>()

const { busy, guard } = useOpsFeedback()

const marketSync = reactive<
  Omit<MarketSyncSettings, 'intraday_job' | 'eod_job'> & {
    intraday_job?: MarketSyncSettings['intraday_job']
    eod_job?: MarketSyncSettings['eod_job']
  }
>({
  enabled_intraday: false,
  interval_minutes: 5,
  enabled_eod: false,
  eod_hour: 16,
  eod_minute: 0,
  workers: 4,
  push_wecom_on_fail: false,
})

async function load(): Promise<void> {
  const ms = await getMarketSyncSettings()
  Object.assign(marketSync, ms)
}

async function saveMarketSync(): Promise<void> {
  const saved = await guard(
    () =>
      saveMarketSyncSettings({
        enabled_intraday: marketSync.enabled_intraday,
        interval_minutes: marketSync.interval_minutes,
        enabled_eod: marketSync.enabled_eod,
        eod_hour: marketSync.eod_hour,
        eod_minute: marketSync.eod_minute,
        workers: marketSync.workers,
        push_wecom_on_fail: marketSync.push_wecom_on_fail,
      }),
    '行情同步设置已保存',
  )
  if (saved) {
    Object.assign(marketSync, saved)
    emit('jobs-changed')
  }
}

async function enableRecommendedSync(): Promise<void> {
  marketSync.enabled_intraday = true
  marketSync.interval_minutes = 5
  marketSync.enabled_eod = true
  marketSync.eod_hour = 16
  marketSync.eod_minute = 0
  await saveMarketSync()
}

defineExpose({ load, enableRecommendedSync })
</script>

<template>
  <Sheet title="行情同步">
    <el-form label-position="top" class="sync-form" @submit.prevent="saveMarketSync">
      <div class="form-grid">
        <el-form-item label="盘中增量">
          <el-switch v-model="marketSync.enabled_intraday" />
          <span class="form-inline-hint">工作日 9–14 点按周期补当日 K（spot）</span>
        </el-form-item>
        <el-form-item label="增量周期（分钟）">
          <el-select v-model="marketSync.interval_minutes" class="full">
            <el-option :value="1" label="1 分钟" />
            <el-option :value="5" label="5 分钟" />
            <el-option :value="15" label="15 分钟" />
            <el-option :value="30" label="30 分钟" />
          </el-select>
        </el-form-item>
        <el-form-item label="日终重刷">
          <el-switch v-model="marketSync.enabled_eod" />
          <span class="form-inline-hint">只刷当日 OHLC，不重拉历史</span>
        </el-form-item>
        <el-form-item label="日终时点">
          <div class="time-row">
            <el-input-number
              v-model="marketSync.eod_hour"
              :min="12"
              :max="23"
              controls-position="right"
            />
            <span>:</span>
            <el-input-number
              v-model="marketSync.eod_minute"
              :min="0"
              :max="59"
              :step="5"
              controls-position="right"
            />
          </div>
        </el-form-item>
        <el-form-item label="并发 workers">
          <el-input-number
            v-model="marketSync.workers"
            :min="1"
            :max="16"
            controls-position="right"
          />
        </el-form-item>
        <el-form-item label="同步失败推企微">
          <el-switch v-model="marketSync.push_wecom_on_fail" />
        </el-form-item>
      </div>
      <div v-if="marketSync.intraday_job || marketSync.eod_job" class="sync-meta">
        <p v-if="marketSync.intraday_job" class="dim mono">
          盘中：{{ marketSync.intraday_job.cron || '—' }} · 下次
          {{ formatNext(marketSync.intraday_job.next_run_at) }}
        </p>
        <p v-if="marketSync.eod_job" class="dim mono">
          日终：{{ marketSync.eod_job.cron || '—' }} · 下次
          {{ formatNext(marketSync.eod_job.next_run_at) }}
        </p>
      </div>
      <el-button type="primary" :disabled="busy" @click="saveMarketSync">保存并装载调度</el-button>
      <el-button :disabled="busy" @click="enableRecommendedSync">一键启用推荐（5 分 + 16:00）</el-button>
    </el-form>
    <p class="form-hint">
      会自动维护「行情盘中增量」「行情日终重刷」两条定时任务。需容器 PALACE_ENABLE_SCHEDULER=1。
    </p>
  </Sheet>
</template>

<style scoped>
.form-inline-hint {
  margin-left: 0.75rem;
  color: var(--mist);
  font-size: 0.8rem;
}

.time-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.sync-meta {
  margin: 0.5rem 0 1rem;
}
</style>
