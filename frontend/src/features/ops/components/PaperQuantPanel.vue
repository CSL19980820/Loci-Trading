<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  absorbPaperStyle,
  explorePaperMemory,
  getPaperCabin,
  listAlertRules,
  rebuildPaperMemory,
  runPaperEod,
  runPaperMonitor,
  saveAlertRule,
  savePaperCabinConfig,
  savePaperStyle,
  scanAlertRules,
  type UnifiedMonitorPool,
} from '@/shared/api/quant_ops_paper'
import {
  getLeaderRoles,
  getNotifySettings,
  saveNotifySettings,
  testNotifySettings,
  type NotifySettings,
} from '@/shared/api/quant_ops'
import type { LeaderRoleHistoryResponse } from '@/shared/types/quant'

import PaperRoleReviewPanel from './PaperRoleReviewPanel.vue'
import { cnStrategyName } from '../composables/opsLabels'

const slug = ref('demo')
const cabinBusy = ref(false)
const cabin = ref<Record<string, unknown> | null>(null)
const positions = ref<Array<Record<string, unknown>>>([])
const fills = ref<Array<Record<string, unknown>>>([])
const monitorRuns = ref<Array<Record<string, unknown>>>([])
const plan = ref<Record<string, unknown> | null>(null)
const unifiedPool = ref<UnifiedMonitorPool | null>(null)
const styleMd = ref('')
const styleRevision = ref(0)
const lessons = ref<Array<Record<string, unknown>>>([])
const leaderRoles = ref<LeaderRoleHistoryResponse | null>(null)
const watchHintsText = ref('')
const memorySummary = ref('')
const memoryNodes = ref<Array<Record<string, unknown>>>([])
const memoryEdges = ref<Array<Record<string, unknown>>>([])
const memoryQuery = ref('高开 教训')
const memoryStats = ref('')

const quietHours = ref('')
const barkEnabled = ref(false)
const barkKey = ref('')
const barkServer = ref('')
const followWecom = ref(false)
const model = ref('')
const thinking = ref('medium')
const maxLayers = ref(4)
const gapUpChase = ref(false)

const alertCode = ref('')
const alertPrice = ref<number | null>(null)
const rules = ref<Array<Record<string, unknown>>>([])

const planItems = computed(() => {
  const items = (unifiedPool.value as { items?: Array<Record<string, unknown>> } | null)?.items
  return Array.isArray(items) ? items : []
})

const latestMarketGate = computed(() => {
  const snapshot = monitorRuns.value[0]?.snapshot
  const gate = (snapshot as { market_gate?: unknown } | undefined)?.market_gate
  return gate && typeof gate === 'object' ? (gate as Record<string, unknown>) : null
})

const latestMarketGateType = computed<'success' | 'warning' | 'info'>(() => {
  if (latestMarketGate.value?.state === 'dragon') return 'success'
  if (latestMarketGate.value?.state === 'empty') return 'warning'
  return 'info'
})

/** 最近盯盘快照中的交易日闸（日历缺失 fail-closed 须可见）。 */
const latestTradingDayGate = computed(() => {
  const snapshot = monitorRuns.value[0]?.snapshot
  const gate = (snapshot as { trading_day_gate?: unknown } | undefined)?.trading_day_gate
  return gate && typeof gate === 'object' ? (gate as Record<string, unknown>) : null
})

const tradingDayGateAlert = computed(() => {
  const gate = latestTradingDayGate.value
  if (!gate) return null
  const buyOk = gate.buy_execution_allowed === true
  const isTrading = gate.is_trading_day === true
  const source = String(gate.calendar_source || '')
  if (buyOk && isTrading) return null
  const type: 'warning' | 'error' | 'info' =
    source === 'weekday_fallback' || (!buyOk && isTrading) ? 'warning' : 'info'
  const title =
    source === 'weekday_fallback'
      ? '交易日历缺失：买入 fail-closed'
      : isTrading
        ? '纸面买入暂不可执行'
        : '今日非交易日'
  return {
    type,
    title,
    // el-alert 禁 description：闸门备注改挂 tooltip，页面上只留 ≤20 字的标题
    note: String(gate.note || '请同步 market.db 交易日历后再开仓'),
  }
})

const roleAlertLessons = computed(() =>
  lessons.value.filter((row) => String(row.kind || '') === 'role_alert'),
)

const regularLessons = computed(() =>
  lessons.value.filter((row) => String(row.kind || '') !== 'role_alert'),
)

function scenarioLabel(row: Record<string, unknown>, key: string): string {
  const scenarios = row.scenarios as Record<string, Record<string, unknown>> | undefined
  const sc = scenarios?.[key]
  if (!sc) return '—'
  const buy = sc.buy ? '买' : '不买'
  return `${buy} ${sc.entry_pct_min}~${sc.entry_pct_max}% · ${sc.layers ?? 0}层`
}

async function loadNotify(): Promise<void> {
  const n: NotifySettings = await getNotifySettings()
  quietHours.value = n.quiet_hours || ''
  barkEnabled.value = Boolean(n.bark?.enabled)
  barkKey.value = n.bark?.device_key || ''
  barkServer.value = n.bark?.server_url || ''
}

async function saveNotify(): Promise<void> {
  await saveNotifySettings({
    quiet_hours: quietHours.value,
    bark: {
      enabled: barkEnabled.value,
      device_key: barkKey.value,
      server_url: barkServer.value,
    },
  })
  ElMessage.success('通知策略已保存')
  await loadNotify()
}

async function testNotify(): Promise<void> {
  await testNotifySettings()
  ElMessage.success('测试推送已发送')
}

async function loadLeaderRoles(slugValue: string): Promise<void> {
  try {
    leaderRoles.value = await getLeaderRoles(slugValue)
  } catch {
    leaderRoles.value = null
  }
}

async function loadCabin(): Promise<void> {
  cabinBusy.value = true
  try {
    const slugValue = slug.value.trim() || 'demo'
    const [data] = await Promise.all([getPaperCabin(slugValue), loadLeaderRoles(slugValue)])
    cabin.value = data.cabin
    positions.value = data.positions
    fills.value = data.fills
    monitorRuns.value = data.monitor_runs
    plan.value = data.nextday_plan
    unifiedPool.value = data.unified_pool ?? null
    const style = data.style as
      | { style_md?: string; revision?: number; watch_hints?: string[] }
      | undefined
    styleMd.value = String(style?.style_md || '')
    styleRevision.value = Number(style?.revision || 0)
    watchHintsText.value = Array.isArray(style?.watch_hints)
      ? style.watch_hints.join('\n')
      : ''
    lessons.value = Array.isArray(data.lessons) ? data.lessons : []
    const graph = data.memory_graph
    memorySummary.value = String(graph?.summary || '')
    memoryNodes.value = Array.isArray(graph?.nodes) ? graph.nodes : []
    memoryEdges.value = Array.isArray(graph?.edges) ? graph.edges : []
    const stats = graph?.stats as { nodes?: number; edges?: number; by_kind?: Record<string, number> } | undefined
    memoryStats.value = stats
      ? `节点 ${stats.nodes ?? 0} · 边 ${stats.edges ?? 0}`
      : ''
    const cfg = (data.cabin.config as { paper_quant?: Record<string, unknown> } | undefined)
      ?.paper_quant
    if (cfg) {
      followWecom.value = Boolean(cfg.follow_wecom)
      model.value = String(cfg.model || '')
      thinking.value = String(cfg.thinking || 'medium')
      gapUpChase.value = Boolean(cfg.gap_up_chase)
    }
    maxLayers.value = Number(data.cabin.max_layers || 4)
  } finally {
    cabinBusy.value = false
  }
}

async function saveStyle(): Promise<void> {
  const hints = watchHintsText.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  await savePaperStyle(slug.value.trim() || 'demo', {
    style_md: styleMd.value,
    watch_hints: hints,
  })
  ElMessage.success('战法风格记忆已保存')
  await loadCabin()
}

async function absorbStyle(): Promise<void> {
  cabinBusy.value = true
  try {
    const result = await absorbPaperStyle(slug.value.trim() || 'demo')
    ElMessage.success(`已吸入 ${String(result.absorbed ?? 0)} 条教训`)
    await loadCabin()
  } finally {
    cabinBusy.value = false
  }
}

async function exploreMemory(): Promise<void> {
  cabinBusy.value = true
  try {
    const result = await explorePaperMemory(slug.value.trim() || 'demo', memoryQuery.value)
    memorySummary.value = String(result.summary || '')
    memoryNodes.value = Array.isArray(result.nodes) ? result.nodes : []
    memoryEdges.value = Array.isArray(result.edges) ? result.edges : []
    const stats = result.stats as { nodes?: number; edges?: number } | undefined
    memoryStats.value = stats ? `节点 ${stats.nodes ?? 0} · 边 ${stats.edges ?? 0}` : ''
  } finally {
    cabinBusy.value = false
  }
}

async function rebuildMemory(): Promise<void> {
  cabinBusy.value = true
  try {
    await rebuildPaperMemory(slug.value.trim() || 'demo')
    ElMessage.success('记忆图已重建')
    await loadCabin()
  } finally {
    cabinBusy.value = false
  }
}

async function saveCabin(): Promise<void> {
  await savePaperCabinConfig(slug.value.trim() || 'demo', {
    enabled: true,
    follow_wecom: followWecom.value,
    model: model.value,
    thinking: thinking.value,
    max_layers: maxLayers.value,
    gap_up_chase: gapUpChase.value,
    ai_apply_paper: true,
    ai_mode: model.value ? 'suggest' : 'rules',
  })
  ElMessage.success('纸面舱配置已保存')
  await loadCabin()
}

async function monitorNow(): Promise<void> {
  cabinBusy.value = true
  try {
    await runPaperMonitor(slug.value.trim() || 'demo')
    ElMessage.success('盯盘已执行')
    await loadCabin()
  } finally {
    cabinBusy.value = false
  }
}

async function eodNow(): Promise<void> {
  cabinBusy.value = true
  try {
    const result = await runPaperEod(slug.value.trim() || 'demo')
    const lb = result.lookback as
      | { days?: string[]; missed?: unknown[]; bought?: unknown[] }
      | undefined
    const miss = Array.isArray(lb?.missed) ? lb.missed.length : 0
    const bought = Array.isArray(lb?.bought) ? lb.bought.length : 0
    ElMessage.success(
      lb?.days?.length
        ? `日终完成：回看 ${lb.days.length} 日 · 买过 ${bought} · 错过 ${miss}`
        : '日终总结已执行',
    )
    await loadCabin()
  } finally {
    cabinBusy.value = false
  }
}

async function loadRules(): Promise<void> {
  rules.value = await listAlertRules()
}

async function addRule(): Promise<void> {
  if (!alertCode.value.trim() || alertPrice.value == null) {
    ElMessage.warning('请填写代码与价格')
    return
  }
  await saveAlertRule({
    code: alertCode.value.trim(),
    name: `${alertCode.value.trim()} 价格提醒`,
    condition_group: {
      op: 'and',
      conditions: [{ type: 'price', op: '>=', value: alertPrice.value }],
    },
  })
  alertCode.value = ''
  alertPrice.value = null
  await loadRules()
  ElMessage.success('规则已保存')
}

async function scanRules(): Promise<void> {
  const result = await scanAlertRules(true)
  ElMessage.info(`试扫命中 ${String(result.triggered ?? 0)} 条`)
}

onMounted(async () => {
  await Promise.all([loadNotify(), loadCabin(), loadRules()])
})
</script>

<template>
  <div class="paper-quant" v-loading="cabinBusy">
    <el-card shadow="never" class="block">
      <template #header>通知策略（安静时段 / Bark）</template>
      <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
        <el-form-item label="安静时段">
          <el-input v-model="quietHours" placeholder="23:00-07:00，空为关闭" />
        </el-form-item>
        <el-form-item label="Bark">
          <el-switch v-model="barkEnabled" />
          <el-input
            v-model="barkKey"
            class="ml"
            placeholder="device_key"
            :disabled="!barkEnabled"
          />
          <el-input
            v-model="barkServer"
            class="ml"
            placeholder="server_url 可选"
            :disabled="!barkEnabled"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveNotify">保存</el-button>
          <el-button @click="testNotify">测试推送</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>纸面量化舱</template>
      <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
        <el-form-item label="战法标识">
          <el-input v-model="slug" style="max-width: 12rem" />
          <!-- slug 是英文编码，展示位必须给中文名：走共享词表（含拼音词根兜底） -->
          <el-tag class="ml" size="small" effect="plain">{{ cnStrategyName('', slug.trim() || 'demo') }}</el-tag>
          <el-button class="ml" @click="loadCabin">刷新</el-button>
        </el-form-item>
        <el-form-item label="企微跟随">
          <el-switch v-model="followWecom" />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="model" placeholder="空则情景门闩（非盲目开仓）" />
        </el-form-item>
        <el-form-item label="思考档">
          <el-select v-model="thinking" style="width: 10rem">
            <el-option label="off" value="off" />
            <el-option label="low" value="low" />
            <el-option label="medium" value="medium" />
            <el-option label="high" value="high" />
          </el-select>
        </el-form-item>
        <el-form-item label="满仓层数">
          <el-input-number v-model="maxLayers" :min="1" :max="20" :step="0.5" />
        </el-form-item>
        <el-form-item label="高开可追">
          <el-tooltip placement="top-start" content="默认不追；开启后只在浅高开时买半层">
            <el-switch v-model="gapUpChase" />
          </el-tooltip>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveCabin">保存舱配置</el-button>
          <!-- 绿是「成功状态」不是动作色：次级动作用 plain 主色，别在同一排里撞出两种色相 -->
          <el-button type="primary" plain @click="monitorNow">立即盯盘</el-button>
          <el-button @click="eodNow">日终总结</el-button>
        </el-form-item>
      </el-form>
      <p class="muted">
        统一监察池：持股 {{ String((unifiedPool as { counts?: { positions?: number } } | null)?.counts?.positions ?? positions.length) }}/3
        · 观察 {{ String((unifiedPool as { counts?: { observe?: number } } | null)?.counts?.observe ?? 0) }}/5
        · 最近成交 {{ fills.length }} · 20万底仓 / 100%
      </p>
      <!-- 交易日闸是真异常：留 el-alert，标题 ≤20 字；备注（note）进 tooltip -->
      <el-tooltip
        v-if="tradingDayGateAlert"
        placement="top-start"
        :content="tradingDayGateAlert.note"
      >
        <el-alert
          class="mt"
          :type="tradingDayGateAlert.type"
          :closable="false"
          show-icon
          :title="tradingDayGateAlert.title"
        />
      </el-tooltip>
      <!-- 龙空龙闸门是状态读数，不报错：从 el-alert 降成一行 chip + 读数，理由进 tooltip -->
      <p v-if="latestMarketGate" class="gate-row mt">
        <el-tag size="small" effect="plain" :type="latestMarketGateType">
          龙空龙闸门 {{ String(latestMarketGate.mode || '观察') }}
        </el-tag>
        <el-tooltip placement="top-start" :content="String(latestMarketGate.reason || '这次没有给出闸门说明')">
          <span class="muted">{{ String(latestMarketGate.label || '—') }}</span>
        </el-tooltip>
      </p>
      <el-table :data="positions" size="small" empty-text="纸面舱还没有持仓，盯盘买进后会记在这里">
        <el-table-column prop="code" label="代码" width="100" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="layers" label="层" width="80" />
        <el-table-column prop="mark_cost" label="标记成本" width="100" />
      </el-table>
      <!--
        次日情景预案是**内容**，不是异常：原来塞进 el-alert 的 description 里。
        改成正文块，标题与预案日期同一行，正文按原样保留换行。
      -->
      <section v-if="plan" class="plan-body mt">
        <p class="plan-body__head">
          <strong>次日情景预案</strong>
          <span class="mono">{{ (plan as { plan_date?: string }).plan_date || '—' }}</span>
        </p>
        <pre class="plan-body__text">{{ String((plan as { body_text?: string }).body_text || '') }}</pre>
      </section>
      <el-table
        v-if="planItems.length"
        class="mt"
        :data="planItems"
        size="small"
        empty-text="这份预案只给了整体判断，没有列到个股"
      >
        <el-table-column prop="code" label="代码" width="90" />
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="action" label="动作" width="80" />
        <el-table-column prop="thesis" label="想法" min-width="120" show-overflow-tooltip />
        <el-table-column label="高开" min-width="120">
          <template #default="{ row }">{{ scenarioLabel(row, 'gap_up') }}</template>
        </el-table-column>
        <el-table-column label="平开" min-width="120">
          <template #default="{ row }">{{ scenarioLabel(row, 'flat') }}</template>
        </el-table-column>
        <el-table-column label="低开" min-width="120">
          <template #default="{ row }">{{ scenarioLabel(row, 'gap_down') }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <PaperRoleReviewPanel :role-data="leaderRoles" :positions="positions" />

    <el-card shadow="never" class="block">
      <template #header>
        <el-tooltip placement="top-start" content="记的是：评头论足 / 该怎么买 / 该看哪些 / 教训">
          <span>战法风格记忆 · rev {{ styleRevision }}</span>
        </el-tooltip>
      </template>
      <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
        <el-form-item label="风格正文">
          <el-input v-model="styleMd" type="textarea" :rows="10" />
        </el-form-item>
        <el-form-item label="该看哪些">
          <el-input
            v-model="watchHintsText"
            type="textarea"
            :rows="3"
            placeholder="每行一条观察点"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveStyle">保存风格</el-button>
          <el-button @click="absorbStyle">吸入未消化教训</el-button>
          <el-button @click="rebuildMemory">重建记忆图</el-button>
        </el-form-item>
      </el-form>
      <el-form inline label-position="left" label-width="6.5em" class="mt" @submit.prevent>
        <el-form-item label="探索词">
          <el-input v-model="memoryQuery" style="width: 14rem" placeholder="如：高开 教训" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" plain @click="exploreMemory">探索子图</el-button>
          <span class="muted ml">{{ memoryStats }}</span>
        </el-form-item>
      </el-form>
      <!-- 记忆图摘要是内容不是异常：从 el-alert(success)+description 降成正文块 -->
      <pre v-if="memorySummary" class="plan-body__text mt">{{ memorySummary }}</pre>
      <el-table :data="memoryNodes" size="small" class="mt" max-height="200" empty-text="还没有记忆节点，先点「重建记忆图」">
        <el-table-column prop="kind" label="类型" width="90" />
        <el-table-column prop="title" label="标题" min-width="120" show-overflow-tooltip />
        <el-table-column prop="body" label="内容" min-width="160" show-overflow-tooltip />
        <el-table-column prop="weight" label="权重" width="70" />
      </el-table>
      <el-tooltip placement="top-start" content="边类型：has_rule / watches / learned_from / absorbed_into / about…">
        <span class="muted">边 {{ memoryEdges.length }} 条</span>
      </el-tooltip>
      <template v-if="roleAlertLessons.length">
        <p class="section dim">角色告警教训</p>
        <el-table
          :data="roleAlertLessons"
          size="small"
          class="role-alert-table"
          empty-text="还没有角色告警，盯盘跑过才会累积"
          max-height="200"
        >
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column label="类型" width="100">
            <template #default>
              <el-tag size="small" type="warning" effect="plain">角色告警</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
          <el-table-column prop="content" label="内容" min-width="200" show-overflow-tooltip />
          <el-table-column label="已吸" width="70">
            <template #default="{ row }">{{ row.absorbed ? '是' : '否' }}</template>
          </el-table-column>
        </el-table>
      </template>
      <p v-if="regularLessons.length || !roleAlertLessons.length" class="section dim">
        {{ roleAlertLessons.length ? '其他教训' : '教训列表' }}
      </p>
      <el-table
        :data="regularLessons"
        size="small"
        empty-text="还没吸入教训，点上面「吸入未消化教训」取一批"
        max-height="240"
      >
        <el-table-column prop="trade_date" label="日期" width="110" />
        <el-table-column prop="kind" label="类型" width="90" />
        <el-table-column prop="title" label="标题" min-width="120" show-overflow-tooltip />
        <el-table-column prop="content" label="内容" min-width="180" show-overflow-tooltip />
        <el-table-column label="已吸" width="70">
          <template #default="{ row }">{{ row.absorbed ? '是' : '否' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>价格提醒规则</template>
      <el-form inline label-position="left" label-width="6.5em" @submit.prevent>
        <el-form-item label="代码">
          <el-input v-model="alertCode" style="width: 8rem" />
        </el-form-item>
        <el-form-item label="价≥">
          <el-input-number v-model="alertPrice" :step="0.01" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="addRule">添加</el-button>
          <el-button @click="scanRules">试扫</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="rules" size="small" empty-text="还没有规则，填好代码与价格后点「添加」">
        <el-table-column prop="code" label="代码" width="100" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="enabled" label="启用" width="70" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.paper-quant {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
}
.block {
  flex: 0 0 auto;
}
.ml {
  margin-left: var(--gap-2);
}
.mt {
  margin-top: var(--gap-2);
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--fs-aux);
}
/* 预案 / 记忆图摘要：正文块，保留原文换行 */
.plan-body {
  padding: var(--gap-2) 0 0;
}
.plan-body__head {
  display: flex;
  align-items: baseline;
  gap: var(--gap-2);
  margin: 0 0 var(--gap-1);
  font-size: var(--fs-aux);
}
.plan-body__text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.45;
  font-family: inherit;
  font-size: var(--fs-aux);
  color: var(--el-text-color-regular);
}
.gate-row {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin: var(--gap-2) 0 0;
}
.mono {
  font-family: var(--mono);
}
.section {
  margin: var(--gap-2) 0 var(--gap-1);
  font-size: var(--fs-aux);
  color: var(--el-text-color-secondary);
}
.role-alert-table :deep(.el-table__row) {
  background: var(--el-color-warning-light-9);
}
</style>
