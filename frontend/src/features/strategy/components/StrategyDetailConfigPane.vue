<script setup lang="ts">
import {
  BOARD_OPTIONS,
  HOUR_OPTS,
  INTERVAL_OPTS,
  MINUTE_OPTS,
  pad,
  type BoardId,
} from './strategyDetailFormat'

export interface StrategyDetailConfigForm {
  boards: Record<BoardId, boolean>
  includeSt: boolean
  scheduleEnabled: boolean
  scheduleMode: 'once' | 'interval'
  pushWecom: boolean
  runHour: number
  runMinute: number
  intervalMinutes: number
  windowStartHour: number
  windowStartMinute: number
  windowEndHour: number
  windowEndMinute: number
}

const props = defineProps<{
  config: StrategyDetailConfigForm
  paramRows: { key: string; label: string; value: string }[]
  loadingJob: boolean
  displayRuns: string[]
}>()

const emit = defineEmits<{
  'patch-config': [partial: Partial<StrategyDetailConfigForm>]
}>()

function patch(partial: Partial<StrategyDetailConfigForm>): void {
  emit('patch-config', partial)
}

function setBoard(id: BoardId, checked: boolean): void {
  emit('patch-config', { boards: { ...props.config.boards, [id]: checked } })
}
</script>

<template>
  <el-form v-loading="loadingJob" class="detail-form" label-position="right" label-width="6.5em" size="small">
    <el-form-item v-if="paramRows.length" label="默认参数">
      <el-descriptions :column="2" size="small" class="param-desc">
        <el-descriptions-item v-for="row in paramRows" :key="row.key" :label="row.label">
          <span class="mono">{{ row.value }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-form-item>
    <el-form-item v-else label="默认参数">
      <span class="dim">无默认参数</span>
    </el-form-item>
    <el-form-item label="行情范围">
      <div class="board-col">
        <div class="board-row">
          <el-checkbox
            v-for="b in BOARD_OPTIONS"
            :key="b.id"
            :model-value="config.boards[b.id]"
            @update:model-value="setBoard(b.id, $event as boolean)"
          >
            {{ b.label }}
          </el-checkbox>
          <el-checkbox
            :model-value="config.includeSt"
            @update:model-value="patch({ includeSt: $event as boolean })"
          >
            含 ST
          </el-checkbox>
        </div>
        <span class="dim hint">定时与手动选股共用；点保存后生效</span>
      </div>
    </el-form-item>
    <el-form-item label="定时选股">
      <el-switch
        :model-value="config.scheduleEnabled"
        @update:model-value="patch({ scheduleEnabled: $event as boolean })"
      />
      <span class="dim hint">开启后按交易日自动跑选股</span>
    </el-form-item>
    <el-form-item label="推送企微">
      <el-switch
        :model-value="config.pushWecom"
        :disabled="!config.scheduleEnabled"
        @update:model-value="patch({ pushWecom: $event as boolean })"
      />
      <span class="dim hint">
        {{
          config.scheduleEnabled
            ? '定时任务结束后自动推送选股结果（需先在运维配置 Webhook）'
            : '先开启定时选股后再开推送'
        }}
      </span>
    </el-form-item>
    <template v-if="config.scheduleEnabled">
      <el-form-item label="方式">
        <el-radio-group
          :model-value="config.scheduleMode"
          @update:model-value="patch({ scheduleMode: $event as 'once' | 'interval' })"
        >
          <el-radio-button value="once">定点</el-radio-button>
          <el-radio-button value="interval">间隔</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="config.scheduleMode === 'once'" label="交易日">
        <div class="time-row">
          <el-select
            :model-value="config.runHour"
            class="time-select"
            @update:model-value="patch({ runHour: $event as number })"
          >
            <el-option v-for="h in HOUR_OPTS" :key="h" :label="pad(h)" :value="h" />
          </el-select>
          <span class="time-sep">:</span>
          <el-select
            :model-value="config.runMinute"
            class="time-select"
            @update:model-value="patch({ runMinute: $event as number })"
          >
            <el-option v-for="m in MINUTE_OPTS" :key="m" :label="pad(m)" :value="m" />
          </el-select>
        </div>
      </el-form-item>
      <template v-else>
        <el-form-item label="时段">
          <div class="time-row">
            <el-select
              :model-value="config.windowStartHour"
              class="time-select"
              @update:model-value="patch({ windowStartHour: $event as number })"
            >
              <el-option
                v-for="h in HOUR_OPTS"
                :key="`s${h}`"
                :label="pad(h)"
                :value="h"
              />
            </el-select>
            <span class="time-sep">:</span>
            <el-select
              :model-value="config.windowStartMinute"
              class="time-select"
              @update:model-value="patch({ windowStartMinute: $event as number })"
            >
              <el-option
                v-for="m in MINUTE_OPTS"
                :key="`sm${m}`"
                :label="pad(m)"
                :value="m"
              />
            </el-select>
            <span class="time-sep dim">—</span>
            <el-select
              :model-value="config.windowEndHour"
              class="time-select"
              @update:model-value="patch({ windowEndHour: $event as number })"
            >
              <el-option
                v-for="h in HOUR_OPTS"
                :key="`e${h}`"
                :label="pad(h)"
                :value="h"
              />
            </el-select>
            <span class="time-sep">:</span>
            <el-select
              :model-value="config.windowEndMinute"
              class="time-select"
              @update:model-value="patch({ windowEndMinute: $event as number })"
            >
              <el-option
                v-for="m in MINUTE_OPTS"
                :key="`em${m}`"
                :label="pad(m)"
                :value="m"
              />
            </el-select>
          </div>
        </el-form-item>
        <el-form-item label="每隔">
          <el-select
            :model-value="config.intervalMinutes"
            class="interval-select"
            @update:model-value="patch({ intervalMinutes: $event as number })"
          >
            <el-option
              v-for="n in INTERVAL_OPTS"
              :key="n"
              :label="`${n} 分钟`"
              :value="n"
            />
          </el-select>
        </el-form-item>
      </template>
      <el-form-item :label="config.scheduleMode === 'once' ? '下次选股' : '近 5 次'">
        <div v-if="displayRuns.length" class="preview-lines">
          <div v-for="row in displayRuns" :key="row" class="preview-line">{{ row }}</div>
        </div>
        <span v-else class="dim">—</span>
      </el-form-item>
    </template>
  </el-form>
</template>

<style scoped>
/* label 色与间距走全局表皮肤（style.components.css），本页不再私调 */
.param-desc { width: 100%; }
.param-desc :deep(.el-descriptions__body) { background: transparent; }
.board-col { display: flex; flex-direction: column; gap: 0.25rem; }
.board-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.15rem 1rem; min-height: 1.75rem; }
.board-col > .hint { margin-left: 0; }
.time-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem; }
.time-select { width: 4.5rem; }
.interval-select { width: 7.5rem; }
.time-sep { padding: 0 0.1rem; }
.preview-lines { display: flex; flex-direction: column; gap: 0.15rem; }
.preview-line, .mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.preview-line { font-size: var(--fs-aux); font-weight: 600; }
.dim { color: var(--mist); font-size: var(--fs-aux); }
.hint { margin-left: 0.55rem; }
</style>
