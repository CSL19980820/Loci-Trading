<script setup lang="ts">
import { computed } from 'vue'
import { X as Close } from '@lucide/vue'

import { vBusy } from '@/shared/directives/busy'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { Pick, ScreenResult, ScreenSkillPreviewResponse } from '@/shared/types/quant'

import ScreenSkillTestReport from './ScreenSkillTestReport.vue'

/**
 * 结果坞 —— 策稿台右侧的输出栏（桌面双栏的右半边；≤980 时是「结果」那一页）。
 *
 *   [助手] [诊断 2] [解释] [选股 7] [回测]       ×
 *   ─────────────────────────────────────────────────
 *   当前分区内容（各自空态）
 *
 * `assist` 槽是 AI 助手；`backtest` 槽是回测面板。两者都由页面注入，这里只管排版。
 */
export type DockTab = 'assist' | 'diag' | 'explain' | 'picks' | 'bt'

const activeTab = defineModel<DockTab>('activeTab', { default: 'explain' })

const props = defineProps<{
  open: boolean
  preview: ScreenSkillPreviewResponse | null
  screenResult: ScreenResult | null
  screenBusy?: boolean
  backtestSlot?: boolean
  assistSlot?: boolean
}>()

const emit = defineEmits<{
  focusLine: [line: number]
  close: []
}>()

const diagnostics = computed(() => props.preview?.diagnostics ?? [])
const errorCount = computed(() => diagnostics.value.filter((item) => item.severity === 'error').length)
const picks = computed<Array<Pick & { signalDate: string }>>(() => {
  const result = props.screenResult
  if (!result?.picks?.length) return []
  return result.picks.map((row) => ({ ...row, signalDate: result.trade_date }))
})
const watchPicks = computed<Array<Pick & { signalDate: string }>>(() => {
  const result = props.screenResult
  if (!result?.watch_picks?.length) return []
  return result.watch_picks.map((row) => ({ ...row, signalDate: result.trade_date }))
})

const tabs = computed<PageTabItem[]>(() => [
  ...(props.assistSlot ? [{ name: 'assist', label: '助手' }] : []),
  { name: 'diag', label: '诊断', badge: errorCount.value || undefined },
  { name: 'explain', label: '解释' },
  { name: 'picks', label: '选股', badge: picks.value.length || undefined },
  ...(props.backtestSlot ? [{ name: 'bt', label: '回测' }] : []),
])

const tabModel = computed({
  get: () => activeTab.value,
  set: (value: string) => {
    activeTab.value = value as DockTab
  },
})

function onDiagClick(line?: number | null): void {
  if (line != null) emit('focusLine', line)
}
</script>

<template>
  <section
    v-if="open"
    class="side-dock"
    :class="{ 'side-dock--backtest': activeTab === 'bt' }"
    aria-label="结果坞"
  >
    <header class="side-dock__bar">
      <PageTabs v-model="tabModel" :items="tabs" variant="pill" dense :sticky="false" aria-label="结果坞分区" class="side-dock__tabs" />
      <Button access="read" variant="ghost" size="icon-xs" aria-label="收起结果面板" @click="emit('close')">
        <Close aria-hidden="true" />
      </Button>
    </header>

    <div v-busy="screenBusy" class="side-dock__body">
      <div v-if="assistSlot" v-show="activeTab === 'assist'" class="dock-pane dock-pane--assist">
        <slot name="assist" />
      </div>

      <div v-show="activeTab === 'diag'" class="dock-pane">
        <EmptyState v-if="!diagnostics.length" description="无诊断" reason="试跑后这里列出编译与数据问题，点一条可跳到对应行" />
        <ul v-else class="diag-list">
          <li v-for="diag in diagnostics" :key="`${diag.code}-${diag.line}-${diag.message}`">
            <Button access="read" variant="ghost" type="button" class="diag-row" @click="onDiagClick(diag.line)">
              <UiBadge :variant="diag.severity === 'error' ? 'stamp' : diag.severity === 'warning' ? 'warn' : 'info'">
                {{ diag.code }}
              </UiBadge>
              <span class="diag-row__msg">{{ diag.message }}</span>
              <small v-if="diag.line != null" class="diag-row__line">L{{ diag.line }}</small>
            </Button>
          </li>
        </ul>
      </div>

      <div v-show="activeTab === 'explain'" class="dock-pane dock-pane--padded">
        <ScreenSkillTestReport :preview="preview" />
      </div>

      <div v-show="activeTab === 'picks'" class="dock-pane">
        <EmptyState
          v-if="!screenBusy && !picks.length && !watchPicks.length"
          description="这个范围没有选出股票"
          reason="可放宽日期或换股票池后再选股"
        />
        <div v-else class="pick-sections">
          <section v-if="picks.length" class="pick-section" aria-label="正式精选">
            <div class="pick-section__title">
              <strong>正式精选</strong>
              <UiBadge variant="default">{{ picks.length }}</UiBadge>
              <span>沿用原战法胜率口径</span>
            </div>
            <Table class="pick-table">
              <TableHeader>
                <TableRow>
                  <TableHead>标的</TableHead>
                  <TableHead class="text-right">信号日</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="row in picks" :key="row.code">
                  <TableCell><StockLink :code="row.code" :name="row.name" :date="row.signalDate" /></TableCell>
                  <TableCell class="num">{{ row.signalDate }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </section>
          <section v-if="watchPicks.length" class="pick-section" aria-label="低吸观察">
            <div class="pick-section__title">
              <strong>低吸观察</strong>
              <UiBadge variant="warn">不计正式胜率</UiBadge>
            </div>
            <Table class="pick-table">
              <TableHeader>
                <TableRow>
                  <TableHead>标的</TableHead>
                  <TableHead class="text-right">信号日</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="row in watchPicks" :key="row.code">
                  <TableCell><StockLink :code="row.code" :name="row.name" :date="row.signalDate" /></TableCell>
                  <TableCell class="num">{{ row.signalDate }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </section>
        </div>
      </div>

      <div v-show="activeTab === 'bt'" class="dock-pane dock-pane--padded dock-pane--bt">
        <slot name="backtest" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.side-dock {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}

.side-dock__bar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-2) var(--gap-2) var(--gap-3);
  border-bottom: 1px solid var(--border-subtle);
}

.side-dock__tabs {
  min-width: 0;
  flex: 1 1 auto;
}

.side-dock__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

.dock-pane {
  min-height: 100%;
}

.dock-pane--padded {
  padding: var(--gap-3);
}

.dock-pane--assist {
  padding: var(--gap-3);
}

.dock-pane--bt {
  container-type: inline-size;
}

/* 诊断 */
.diag-list {
  margin: 0;
  padding: var(--gap-1) 0;
  list-style: none;
}

.diag-row {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-height: var(--row-h);
  padding: 6px var(--gap-3);
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.diag-row:hover {
  background: var(--surface-hover);
}

.diag-row:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: -2px;
}

.diag-row__msg {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  overflow-wrap: anywhere;
}

.diag-row__line {
  flex-shrink: 0;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

/* 选股 */
.pick-sections {
  display: flex;
  flex-direction: column;
}

.pick-section + .pick-section {
  border-top: 1px solid var(--border-subtle);
}

.pick-section__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.pick-section__title strong {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
}

.pick-table :deep(th) {
  height: var(--head-h);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
}

.pick-table :deep(td) {
  height: var(--row-h);
  font-size: var(--fs-ui);
}

.pick-table :deep(th:first-child),
.pick-table :deep(td:first-child) {
  padding-left: var(--gap-3);
}

.pick-table :deep(th:last-child),
.pick-table :deep(td:last-child) {
  padding-right: var(--gap-3);
}

.num {
  text-align: right;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}
</style>
