<script setup lang="ts">
import type { MarketSyncSettings } from '@/shared/types/quant'
import type { SyncDraft } from '../composables/useSystemSettings'
import { formatNext } from '../composables/opsLabels'

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
  <el-form class="sys-form" label-position="left" label-width="5.5rem" @submit.prevent>
    <el-row :gutter="12">
      <el-col :xs="24" :xl="12">
        <el-form-item label="盘中增量">
          <div class="inline-row">
            <el-switch v-model="sync.enabled_intraday" />
            <el-select
              v-model="sync.interval_minutes"
              class="interval"
              :disabled="!sync.enabled_intraday"
            >
              <el-option :value="1" label="每 1 分钟" />
              <el-option :value="5" label="每 5 分钟" />
              <el-option :value="15" label="每 15 分钟" />
              <el-option :value="30" label="每 30 分钟" />
            </el-select>
            <span class="hint">工作日 9–14 点</span>
          </div>
        </el-form-item>
      </el-col>
      <el-col :xs="24" :xl="12">
        <el-form-item label="日终重刷">
          <div class="inline-row">
            <el-switch v-model="sync.enabled_eod" />
            <el-input-number
              v-model="sync.eod_hour"
              :min="12"
              :max="23"
              :disabled="!sync.enabled_eod"
              controls-position="right"
            />
            <span class="time-sep">:</span>
            <el-input-number
              v-model="sync.eod_minute"
              :min="0"
              :max="59"
              :step="5"
              :disabled="!sync.enabled_eod"
              controls-position="right"
            />
            <span v-if="nextRun()" class="hint">下次 {{ nextRun() }}</span>
          </div>
        </el-form-item>
      </el-col>
      <el-col :xs="24" :sm="12" :md="10">
        <el-form-item label="并发">
          <div class="inline-row">
            <el-input-number
              v-model="sync.workers"
              :min="1"
              :max="16"
              controls-position="right"
            />
            <el-button size="small" @click="emit('recommend')">推荐配置</el-button>
          </div>
        </el-form-item>
      </el-col>
    </el-row>
  </el-form>
</template>

<style scoped>
.inline-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.5rem;
}

.interval {
  width: 8.25rem;
}

.time-sep {
  color: var(--mist);
  font-family: var(--mono);
}

.hint {
  color: var(--mist);
  font-size: 0.78rem;
}

.sys-form :deep(.el-form-item) {
  margin-bottom: 0.45rem;
}
</style>
