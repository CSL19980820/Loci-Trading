<script setup lang="ts">
/** 战法调度与范围：股票池板块 → 定时选股（定点 / 间隔）→ 推送。保存由外层对话框统一提交。 */
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'

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

function runLabel(raw: string): string {
  return raw.length > 11 ? raw.slice(5) : raw
}
</script>

<template>
  <div class="cfg">
    <PageBusy :busy="loadingJob" overlay />

    <section class="cfg__group" aria-label="股票池">
      <div class="cfg__row">
        <span class="cfg__label">股票池</span>
        <div class="cfg__chips" role="group" aria-label="板块">
          <button
            v-for="b in BOARD_OPTIONS"
            :key="b.id"
            type="button"
            class="cfg__chip"
            :class="{ 'is-on': config.boards[b.id] }"
            :aria-pressed="config.boards[b.id]"
            @click="setBoard(b.id, !config.boards[b.id])"
          >
            {{ b.label }}
          </button>
          <span class="cfg__divider" aria-hidden="true" />
          <button
            type="button"
            class="cfg__chip"
            :class="{ 'is-on': config.includeSt }"
            :aria-pressed="config.includeSt"
            @click="patch({ includeSt: !config.includeSt })"
          >
            含 ST
          </button>
        </div>
      </div>
    </section>

    <section class="cfg__group" aria-label="定时">
      <div class="cfg__row">
        <span class="cfg__label">定时选股</span>
        <Switch
          :model-value="config.scheduleEnabled"
          aria-label="定时选股"
          @update:model-value="(value) => patch({ scheduleEnabled: value })"
        />
      </div>

      <template v-if="config.scheduleEnabled">
        <div class="cfg__row">
          <span class="cfg__label">方式</span>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            :model-value="config.scheduleMode"
            aria-label="定时方式"
            @update:model-value="(value) => { if (value) patch({ scheduleMode: value as 'once' | 'interval' }) }"
          >
            <ToggleGroupItem value="once">交易日定点</ToggleGroupItem>
            <ToggleGroupItem value="interval">盘中间隔</ToggleGroupItem>
          </ToggleGroup>
        </div>

        <div v-if="config.scheduleMode === 'once'" class="cfg__row">
          <span class="cfg__label">时点</span>
          <div class="cfg__time">
            <Select :model-value="config.runHour" @update:model-value="(value) => patch({ runHour: Number(value) })">
              <SelectTrigger size="sm" class="cfg__select" aria-label="小时"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="h in HOUR_OPTS" :key="h" :value="h">{{ pad(h) }}</SelectItem>
              </SelectContent>
            </Select>
            <span class="cfg__sep">:</span>
            <Select :model-value="config.runMinute" @update:model-value="(value) => patch({ runMinute: Number(value) })">
              <SelectTrigger size="sm" class="cfg__select" aria-label="分钟"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="m in MINUTE_OPTS" :key="m" :value="m">{{ pad(m) }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <template v-else>
          <div class="cfg__row">
            <span class="cfg__label">时段</span>
            <div class="cfg__time">
              <Select :model-value="config.windowStartHour" @update:model-value="(value) => patch({ windowStartHour: Number(value) })">
                <SelectTrigger size="sm" class="cfg__select" aria-label="起始小时"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="h in HOUR_OPTS" :key="`s${h}`" :value="h">{{ pad(h) }}</SelectItem>
                </SelectContent>
              </Select>
              <span class="cfg__sep">:</span>
              <Select :model-value="config.windowStartMinute" @update:model-value="(value) => patch({ windowStartMinute: Number(value) })">
                <SelectTrigger size="sm" class="cfg__select" aria-label="起始分钟"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="m in MINUTE_OPTS" :key="`sm${m}`" :value="m">{{ pad(m) }}</SelectItem>
                </SelectContent>
              </Select>
              <span class="cfg__sep">—</span>
              <Select :model-value="config.windowEndHour" @update:model-value="(value) => patch({ windowEndHour: Number(value) })">
                <SelectTrigger size="sm" class="cfg__select" aria-label="结束小时"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="h in HOUR_OPTS" :key="`e${h}`" :value="h">{{ pad(h) }}</SelectItem>
                </SelectContent>
              </Select>
              <span class="cfg__sep">:</span>
              <Select :model-value="config.windowEndMinute" @update:model-value="(value) => patch({ windowEndMinute: Number(value) })">
                <SelectTrigger size="sm" class="cfg__select" aria-label="结束分钟"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="m in MINUTE_OPTS" :key="`em${m}`" :value="m">{{ pad(m) }}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div class="cfg__row">
            <span class="cfg__label">间隔</span>
            <Select :model-value="config.intervalMinutes" @update:model-value="(value) => patch({ intervalMinutes: Number(value) })">
              <SelectTrigger size="sm" class="cfg__select cfg__select--wide" aria-label="间隔分钟"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="n in INTERVAL_OPTS" :key="n" :value="n">每 {{ n }} 分钟</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </template>

        <div class="cfg__row">
          <span class="cfg__label">{{ config.scheduleMode === 'once' ? '下次' : '接下来' }}</span>
          <div v-if="displayRuns.length" class="cfg__runs">
            <span v-for="row in displayRuns" :key="row" class="cfg__run">{{ runLabel(row) }}</span>
          </div>
          <span v-else class="cfg__muted">—</span>
        </div>
      </template>

      <div class="cfg__row">
        <span class="cfg__label">推送企微</span>
        <Switch
          :model-value="config.pushWecom"
          :disabled="!config.scheduleEnabled"
          aria-label="推送企微"
          @update:model-value="(value) => patch({ pushWecom: value })"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.cfg {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.cfg__group {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.cfg__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  min-height: 52px;
  padding: 10px 16px;
}

.cfg__row + .cfg__row {
  border-top: 1px solid var(--border-subtle);
}

.cfg__label {
  flex: none;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 550;
}

.cfg__chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.cfg__chip {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.cfg__chip:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.cfg__chip.is-on {
  border-color: var(--seal-border);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
}

.cfg__chip:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}

.cfg__chip:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.cfg__divider {
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: var(--border-default);
}

.cfg__time {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.cfg__select {
  width: 4.75rem;
}

.cfg__select--wide {
  width: 8rem;
}

.cfg__sep {
  padding: 0 2px;
  color: var(--text-tertiary);
}

.cfg__runs {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.cfg__run {
  padding: 0 8px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--text-primary);
  font: 500 var(--fs-kicker) / 22px var(--mono);
  font-variant-numeric: tabular-nums;
}

.cfg__muted {
  color: var(--text-tertiary);
}
</style>
