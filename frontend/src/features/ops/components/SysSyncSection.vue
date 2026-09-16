<script setup lang="ts">
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
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
  <el-form class="sys-form" label-position="right" label-width="6.5em" size="small" @submit.prevent>
    <el-row :gutter="12">
      <el-col :xs="24" :xl="12">
        <el-form-item label="盘中增量">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <el-switch v-model="sync.enabled_intraday" aria-label="启用盘中增量同步" />
            <!-- 「工作日 9–14 点」是规则不是读数：常驻文字删掉，挂到它约束的那个下拉上 -->
            <el-tooltip placement="top-start" content="只在工作日 9–14 点之间按这个间隔跑">
              <el-select
                v-model="sync.interval_minutes"
                aria-label="盘中同步间隔"
                class="interval"
                :disabled="!sync.enabled_intraday"
              >
                <el-option :value="1" label="每 1 分钟" />
                <el-option :value="5" label="每 5 分钟" />
                <el-option :value="15" label="每 15 分钟" />
                <el-option :value="30" label="每 30 分钟" />
              </el-select>
            </el-tooltip>
          </div>
        </el-form-item>
      </el-col>
      <el-col :xs="24" :xl="12">
        <el-form-item label="日终重刷">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <el-switch v-model="sync.enabled_eod" aria-label="启用日终重刷" />
            <el-input-number
              v-model="sync.eod_hour"
              aria-label="日终重刷小时"
              :min="12"
              :max="23"
              :disabled="!sync.enabled_eod"
              controls-position="right"
            />
            <span class="time-sep">:</span>
            <el-input-number
              v-model="sync.eod_minute"
              aria-label="日终重刷分钟"
              :min="0"
              :max="59"
              :step="5"
              :disabled="!sync.enabled_eod"
              controls-position="right"
            />
            <!-- 「下次 09:30」是数据不是介绍，保留；换成行内读数，与控件同排 -->
            <HeaderStat v-if="nextRun()" label="下次" :value="nextRun()" />
          </div>
        </el-form-item>
      </el-col>
      <el-col :xs="24" :sm="12" :md="10">
        <el-form-item label="并发">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
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
/* 行内控件组：自动换行，横向 12px、纵向 4px。 */

.interval {
  width: 8.25rem;
}

.time-sep {
  color: var(--mist);
  font-family: var(--mono);
}

.sys-form :deep(.el-form-item) {
  margin-bottom: var(--gap-2);
}
</style>
