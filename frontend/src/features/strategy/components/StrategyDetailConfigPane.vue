<script setup lang="ts">
import { useId } from 'vue'

import { Checkbox } from '@/shared/components/ui/checkbox'
import { Label } from '@/shared/components/ui/label'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'

import StrategyField from './StrategyField.vue'
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

/** 勾选框与它的文字标签要绑定，同一页出现两份配置面板时 id 也不能撞 */
const uid = useId()

function patch(partial: Partial<StrategyDetailConfigForm>): void {
  emit('patch-config', partial)
}

function setBoard(id: BoardId, checked: boolean): void {
  emit('patch-config', { boards: { ...props.config.boards, [id]: checked } })
}
</script>

<template>
  <div class="detail-form relative">
    <PageBusy :busy="loadingJob" overlay />
    <StrategyField label="默认参数" inline>
      <dl v-if="paramRows.length" class="param-desc">
        <div v-for="row in paramRows" :key="row.key" class="param-item">
          <dt class="dim">{{ row.label }}</dt>
          <dd class="mono">{{ row.value }}</dd>
        </div>
      </dl>
      <span v-else class="dim">无默认参数</span>
    </StrategyField>

    <StrategyField label="行情范围" inline>
      <div class="board-col">
        <div class="board-row">
          <div v-for="b in BOARD_OPTIONS" :key="b.id" class="board-item">
            <Checkbox
              :id="`${uid}-board-${b.id}`"
              :model-value="config.boards[b.id]"
              @update:model-value="(value) => setBoard(b.id, value === true)"
            />
            <Label :for="`${uid}-board-${b.id}`" class="cursor-pointer">{{ b.label }}</Label>
          </div>
          <div class="board-item">
            <Checkbox
              :id="`${uid}-board-st`"
              :model-value="config.includeSt"
              @update:model-value="(value) => patch({ includeSt: value === true })"
            />
            <Label :for="`${uid}-board-st`" class="cursor-pointer">含 ST</Label>
          </div>
        </div>
        <span class="dim hint">定时与手动选股共用；点保存后生效</span>
      </div>
    </StrategyField>

    <StrategyField label="定时选股" inline>
      <div class="field-row">
        <Switch
          :model-value="config.scheduleEnabled"
          aria-label="定时选股"
          @update:model-value="(value) => patch({ scheduleEnabled: value })"
        />
        <span class="dim hint">开启后按交易日自动跑选股</span>
      </div>
    </StrategyField>

    <StrategyField label="推送企微" inline>
      <div class="field-row">
        <Switch
          :model-value="config.pushWecom"
          :disabled="!config.scheduleEnabled"
          aria-label="推送企微"
          @update:model-value="(value) => patch({ pushWecom: value })"
        />
        <span class="dim hint">
          {{
            config.scheduleEnabled
              ? '定时任务结束后自动推送选股结果（需先在运维配置 Webhook）'
              : '先开启定时选股后再开推送'
          }}
        </span>
      </div>
    </StrategyField>

    <template v-if="config.scheduleEnabled">
      <StrategyField label="方式" inline>
        <ToggleGroup
          type="single"
          variant="outline"
          :model-value="config.scheduleMode"
          aria-label="定时方式"
          @update:model-value="(value) => patch({ scheduleMode: value as 'once' | 'interval' })"
        >
          <ToggleGroupItem value="once">定点</ToggleGroupItem>
          <ToggleGroupItem value="interval">间隔</ToggleGroupItem>
        </ToggleGroup>
      </StrategyField>

      <StrategyField v-if="config.scheduleMode === 'once'" label="交易日" inline>
        <div class="time-row">
          <Select
            :model-value="config.runHour"
            @update:model-value="(value) => patch({ runHour: Number(value) })"
          >
            <SelectTrigger size="sm" class="time-select" aria-label="小时">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="h in HOUR_OPTS" :key="h" :value="h">{{ pad(h) }}</SelectItem>
            </SelectContent>
          </Select>
          <span class="time-sep">:</span>
          <Select
            :model-value="config.runMinute"
            @update:model-value="(value) => patch({ runMinute: Number(value) })"
          >
            <SelectTrigger size="sm" class="time-select" aria-label="分钟">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="m in MINUTE_OPTS" :key="m" :value="m">{{ pad(m) }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </StrategyField>

      <template v-else>
        <StrategyField label="时段" inline>
          <div class="time-row">
            <Select
              :model-value="config.windowStartHour"
              @update:model-value="(value) => patch({ windowStartHour: Number(value) })"
            >
              <SelectTrigger size="sm" class="time-select" aria-label="起始小时">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="h in HOUR_OPTS" :key="`s${h}`" :value="h">{{ pad(h) }}</SelectItem>
              </SelectContent>
            </Select>
            <span class="time-sep">:</span>
            <Select
              :model-value="config.windowStartMinute"
              @update:model-value="(value) => patch({ windowStartMinute: Number(value) })"
            >
              <SelectTrigger size="sm" class="time-select" aria-label="起始分钟">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="m in MINUTE_OPTS" :key="`sm${m}`" :value="m">{{ pad(m) }}</SelectItem>
              </SelectContent>
            </Select>
            <span class="time-sep dim">—</span>
            <Select
              :model-value="config.windowEndHour"
              @update:model-value="(value) => patch({ windowEndHour: Number(value) })"
            >
              <SelectTrigger size="sm" class="time-select" aria-label="结束小时">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="h in HOUR_OPTS" :key="`e${h}`" :value="h">{{ pad(h) }}</SelectItem>
              </SelectContent>
            </Select>
            <span class="time-sep">:</span>
            <Select
              :model-value="config.windowEndMinute"
              @update:model-value="(value) => patch({ windowEndMinute: Number(value) })"
            >
              <SelectTrigger size="sm" class="time-select" aria-label="结束分钟">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="m in MINUTE_OPTS" :key="`em${m}`" :value="m">{{ pad(m) }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </StrategyField>

        <StrategyField label="每隔" inline>
          <Select
            :model-value="config.intervalMinutes"
            @update:model-value="(value) => patch({ intervalMinutes: Number(value) })"
          >
            <SelectTrigger size="sm" class="interval-select" aria-label="间隔分钟">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="n in INTERVAL_OPTS" :key="n" :value="n">{{ n }} 分钟</SelectItem>
            </SelectContent>
          </Select>
        </StrategyField>
      </template>

      <StrategyField :label="config.scheduleMode === 'once' ? '下次选股' : '近 5 次'" inline>
        <div v-if="displayRuns.length" class="preview-lines">
          <div v-for="row in displayRuns" :key="row" class="preview-line">{{ row }}</div>
        </div>
        <span v-else class="dim">—</span>
      </StrategyField>
    </template>
  </div>
</template>

<style scoped>
/* label 色与间距走全局表皮肤（style.components.css），本页不再私调 */
.detail-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.param-desc {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.35rem 1rem;
  margin: 0;
  width: 100%;
}
.param-item {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  min-width: 0;
}
.param-item dd {
  margin: 0;
}
.board-col { display: flex; flex-direction: column; gap: 0.25rem; }
.board-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.15rem 1rem; min-height: 1.75rem; }
.board-item { display: flex; align-items: center; gap: 0.35rem; }
.board-col > .hint { margin-left: 0; }
.field-row { display: flex; flex-wrap: wrap; align-items: center; }
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
