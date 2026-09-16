<script setup lang="ts">
/**
 * 纸面舱卡：舱配置表单 + 两道闸门读数 + 持仓 + 次日情景预案。
 *
 * 与风格记忆卡共读同一个 usePaperCabin 实例（同一份 paper-cabin 响应），所以
 * store 由面板建好后按 prop 传进来；这张卡只负责把结论摆上去。
 */
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'

import SettingsPanel from './SettingsPanel.vue'
import { cnStrategyName } from '../composables/opsLabels'
import type { PaperCabinStore } from '../composables/usePaperCabin'

const props = defineProps<{ cabin: PaperCabinStore }>()

const {
  slug,
  followWecom,
  model,
  thinking,
  maxLayers,
  gapUpChase,
  unifiedPool,
  positions,
  fills,
  plan,
  planItems,
  latestMarketGate,
  latestMarketGateType,
  tradingDayGateAlert,
  scenarioLabel,
  loadCabin,
  saveCabin,
  monitorNow,
  eodNow,
} = props.cabin

const poolCounts = computed(() => {
  const counts = (unifiedPool.value as { counts?: { positions?: number; observe?: number } } | null)?.counts
  return {
    positions: counts?.positions ?? positions.value.length,
    observe: counts?.observe ?? 0,
    fills: fills.value.length,
  }
})

const receipt = computed(() => [
  { key: '持股', value: `${poolCounts.value.positions}/3` },
  { key: '观察', value: `${poolCounts.value.observe}/5` },
  { key: '成交', value: String(poolCounts.value.fills) },
])

const positionRows = computed(() => positions.value as unknown as Record<string, unknown>[])
const planRows = computed(() => planItems.value as unknown as Record<string, unknown>[])

const positionColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 100 },
  { prop: 'name', label: '名称', minWidth: 120 },
  { prop: 'layers', label: '层', width: 80 },
  { prop: 'mark_cost', label: '标记成本', width: 100 },
]

const planColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 100 },
  { prop: 'action', label: '动作', width: 80 },
  { prop: 'thesis', label: '想法', minWidth: 120, showOverflowTooltip: true },
  { prop: 'gap_up', label: '高开', minWidth: 120, slotName: 'gap_up' },
  { prop: 'flat', label: '平开', minWidth: 120, slotName: 'flat' },
  { prop: 'gap_down', label: '低开', minWidth: 120, slotName: 'gap_down' },
]
</script>

<template>
  <SettingsPanel title="纸面量化舱" :receipt="receipt">
    <template #action>
      <el-button size="small" @click="loadCabin">刷新</el-button>
      <el-button type="primary" size="small" @click="saveCabin">保存舱配置</el-button>
      <el-button type="primary" plain size="small" @click="monitorNow">立即盯盘</el-button>
      <el-button size="small" @click="eodNow">日终总结</el-button>
    </template>

    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <el-form-item label="战法标识">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <el-input v-model="slug" class="max-w-48" />
          <el-tag size="small" effect="plain">{{ cnStrategyName('', slug.trim() || 'demo') }}</el-tag>
        </div>
      </el-form-item>
      <el-form-item label="企微跟随">
        <el-switch v-model="followWecom" aria-label="启用企微跟随" />
      </el-form-item>
      <el-form-item label="模型">
        <el-input v-model="model" placeholder="空则情景门闩（非盲目开仓）" />
      </el-form-item>
      <el-form-item label="思考档">
        <el-select v-model="thinking" class="w-40">
          <el-option label="off" value="off" />
          <el-option label="low" value="low" />
          <el-option label="medium" value="medium" />
          <el-option label="high" value="high" />
        </el-select>
      </el-form-item>
      <el-form-item label="满仓层数">
        <el-input-number v-model="maxLayers" :min="1" :max="20" :step="0.5" />
      </el-form-item>
      <el-form-item label="高开可追" class="mb-0">
        <el-tooltip placement="top-start" content="默认不追；开启后只在浅高开时买半层">
          <el-switch v-model="gapUpChase" aria-label="允许浅高开追入半层" />
        </el-tooltip>
      </el-form-item>
    </el-form>

    <p class="text-aux text-mist m-0 mt-2">统一监察池 · 20万底仓 / 100%</p>

    <el-tooltip
      v-if="tradingDayGateAlert"
      placement="top-start"
      :content="tradingDayGateAlert.note"
    >
      <el-alert
        class="mt-2"
        :type="tradingDayGateAlert.type"
        :closable="false"
        show-icon
        :title="tradingDayGateAlert.title"
      />
    </el-tooltip>

    <p v-if="latestMarketGate" class="mt-2 flex flex-wrap items-center gap-2">
      <el-tag size="small" effect="plain" :type="latestMarketGateType">
        龙空龙闸门 {{ String(latestMarketGate.mode || '观察') }}
      </el-tag>
      <el-tooltip placement="top-start" :content="String(latestMarketGate.reason || '这次没有给出闸门说明')">
        <span class="text-aux text-mist">{{ String(latestMarketGate.label || '—') }}</span>
      </el-tooltip>
    </p>

    <BasicTable
      class="mt-2"
      :columns="positionColumns"
      :data-source="positionRows"
      :pagination="false"
      row-key="code"
      stripe
      empty-text="纸面舱还没有持仓"
      empty-reason="盯盘买进后会记在这里"
    />

    <section v-if="plan" class="mt-2">
      <p class="text-aux m-0 mb-1 flex items-baseline gap-2">
        <strong>次日情景预案</strong>
        <span class="font-mono">{{ (plan as { plan_date?: string }).plan_date || '—' }}</span>
      </p>
      <pre class="paper-plan">{{ String((plan as { body_text?: string }).body_text || '') }}</pre>
    </section>

    <BasicTable
      v-if="planItems.length"
      class="mt-2"
      :columns="planColumns"
      :data-source="planRows"
      :pagination="false"
      row-key="code"
      stripe
      empty-text="这份预案只给了整体判断"
      empty-reason="没有列到个股"
    >
      <template #gap_up="{ row }">{{ scenarioLabel(row, 'gap_up') }}</template>
      <template #flat="{ row }">{{ scenarioLabel(row, 'flat') }}</template>
      <template #gap_down="{ row }">{{ scenarioLabel(row, 'gap_down') }}</template>
    </BasicTable>
  </SettingsPanel>
</template>

<style scoped>
.paper-plan { padding: var(--gap-3); margin: 0; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface-sunken); color: var(--ink); font: var(--fs-body)/1.6 var(--font); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
