<script setup lang="ts">
import { computed } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import type { Pick, ScreenResult, ScreenSkillPreviewResponse } from '@/shared/types/quant'

import ScreenSkillTestReport from './ScreenSkillTestReport.vue'

export type DockTab = 'diag' | 'explain' | 'picks' | 'bt'

const activeTab = defineModel<DockTab>('activeTab', { default: 'explain' })

const props = defineProps<{
  open: boolean
  preview: ScreenSkillPreviewResponse | null
  screenResult: ScreenResult | null
  screenBusy?: boolean
  backtestSlot?: boolean
}>()

const emit = defineEmits<{
  focusLine: [line: number]
}>()

const diagnostics = computed(() => props.preview?.diagnostics ?? [])
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

const hasErrorDiag = computed(() =>
  diagnostics.value.some((item) => item.severity === 'error'),
)

function onDiagClick(line?: number | null): void {
  if (line != null) emit('focusLine', line)
}
</script>

<template>
  <section
    class="report-dock"
    :class="{ 'report-dock--open': open }"
    aria-label="结果坞"
  >
    <div v-if="open" class="report-dock__toolbar">
      <el-radio-group v-model="activeTab" size="small">
        <el-radio-button value="diag">
          诊断
          <template v-if="hasErrorDiag"> · {{ diagnostics.filter((d) => d.severity === 'error').length }}</template>
        </el-radio-button>
        <el-radio-button value="explain">解释</el-radio-button>
        <el-radio-button value="picks">选股</el-radio-button>
        <el-radio-button v-if="backtestSlot" value="bt">回测</el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="open" v-loading="screenBusy" class="report-dock__body">
      <div v-show="activeTab === 'diag'" class="dock-pane">
        <el-empty
          v-if="!diagnostics.length"
          :image-size="40"
          description="无诊断"
        />
        <el-button
          v-for="diag in diagnostics"
          :key="`${diag.code}-${diag.line}-${diag.message}`"
          text
          class="dock-diag"
          @click="onDiagClick(diag.line)"
        >
          <el-tag
            size="small"
            :type="diag.severity === 'error' ? 'danger' : diag.severity === 'warning' ? 'warning' : 'info'"
            effect="plain"
          >
            {{ diag.code }}
          </el-tag>
          <span>{{ diag.message }}</span>
          <small v-if="diag.line != null">L{{ diag.line }}</small>
        </el-button>
      </div>

      <div v-show="activeTab === 'explain'" class="dock-pane">
        <ScreenSkillTestReport :preview="preview" />
      </div>

      <div v-show="activeTab === 'picks'" class="dock-pane">
        <EmptyState
          v-if="!screenBusy && !picks.length && !watchPicks.length"
          description="这个范围没有选出股票"
          reason="可放宽日期或换股票池后再选股"
          :image-size="48"
        />
        <div v-else class="pick-sections">
          <section v-if="picks.length" class="pick-section">
            <div class="pick-section__title">
              <strong>正式精选</strong>
              <span class="mist">沿用原战法胜率口径</span>
            </div>
            <el-table :data="picks" size="small" stripe>
              <el-table-column label="代码" min-width="96">
                <template #default="{ row }">
                  <StockLink :code="row.code" :date="row.signalDate" />
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" min-width="108" />
              <el-table-column prop="signalDate" label="信号日" width="118" />
            </el-table>
          </section>
          <section v-if="watchPicks.length" class="pick-section">
            <div class="pick-section__title">
              <strong>低吸观察</strong>
              <el-tag size="small" type="warning" effect="plain">不计正式胜率</el-tag>
            </div>
            <el-table :data="watchPicks" size="small" stripe>
              <el-table-column label="代码" min-width="96">
                <template #default="{ row }">
                  <StockLink :code="row.code" :date="row.signalDate" />
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" min-width="108" />
              <el-table-column prop="signalDate" label="信号日" width="118" />
            </el-table>
          </section>
        </div>
      </div>

      <div v-show="activeTab === 'bt'" class="dock-pane dock-pane--bt">
        <slot name="backtest" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.report-dock {
  display: grid;
  grid-template-rows: 0fr;
  flex: 0 0 0;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-top: 0;
  background: var(--sheet);
  transition: flex-basis 0.15s ease;
}

.report-dock--open {
  grid-template-rows: 2.35rem minmax(0, 1fr);
  flex: 0 0 min(14.5rem, 40%);
  border-top: 1px solid var(--rule);
}

.report-dock__toolbar {
  display: flex;
  align-items: center;
  padding: 0.35rem 0.7rem;
  border-bottom: 1px solid var(--rule);
  background: var(--panel-2);
}

.report-dock__body {
  min-height: 0;
  overflow: auto;
  padding: 0.55rem 0.7rem 0.7rem;
}

.dock-pane {
  min-height: 8rem;
  height: 100%;
}

.pick-sections {
  display: grid;
  gap: 0.65rem;
}

.pick-section__title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding-bottom: 0.3rem;
}

.dock-diag {
  display: flex !important;
  align-items: baseline;
  flex-wrap: wrap;
  justify-content: flex-start;
  gap: 0.35rem;
  width: 100%;
  height: auto !important;
  margin: 0 0 0.35rem !important;
  padding: 0.35rem 0.4rem !important;
  text-align: left;
  white-space: normal;
}

.dock-diag:hover {
  background: var(--seal-soft);
}

.dock-diag small {
  color: var(--mist);
  font-family: var(--mono);
}
</style>
