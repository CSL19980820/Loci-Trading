<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
/**
 * 战法监测预览：用实时数据试跑一次确定性扫描。
 *
 * 与定时监测同一套规则，但只读——不落纸面舱、不推送、不调 LLM。
 * 悟道 MCP 未装配时整块置灰，不发请求也不消耗配额。
 */
import { computed, ref, type Component } from 'vue'
import { Info, TriangleAlert } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { getLeaderRoles, previewSkillWatch } from '@/shared/api/quant_ops'
import { toErrorMessage } from '@/shared/lib/errors'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type { LeaderRoleSummary, SkillWatchPreview, WatchTuningSuggestion } from '@/shared/types/quant'

import { badgeTone, type StrategyBadgeTone } from './strategyBadge'

const props = defineProps<{
  slug: string
  available: boolean
  unavailableReason?: string
}>()

const running = ref(false)
const preview = ref<SkillWatchPreview | null>(null)
const roleSummary = ref<LeaderRoleSummary | null>(null)
const roleSuggestions = ref<WatchTuningSuggestion[]>([])

const SIGNAL_LABEL: Record<string, string> = {
  paper_candidate: '纸面候选·未验证',
  leader_watch: '龙头·未验证',
  leader_weak: '龙头走弱',
  gate_empty: '空仓窗口',
  invalidated: '形态失效',
  watch_only: '观察',
  buy_hint: '候选信号·未验证',
  sell_hint: '风险信号·未验证',
}

/** 角色语气：成功走 ok、走弱走 warn、结构破坏走印章红（红绿只留给价格） */
type BadgeTone = StrategyBadgeTone

const ROLE_TONE: Record<string, BadgeTone> = {
  leader: 'ok',
  secondary: 'info',
  follower: 'info',
  weakened: 'warn',
  failed: 'stamp',
}

const ROLE_LABEL: Record<string, string> = {
  leader: '龙头',
  secondary: '中军',
  follower: '跟风',
  weakened: '走弱',
  failed: '结构破坏',
}

const gate = computed(() => preview.value?.market_gate ?? null)

const gateTone = computed<BadgeTone>(() => {
  const state = gate.value?.state
  if (state === 'dragon') return 'ok'
  if (state === 'empty') return 'warn'
  return 'info'
})

const gateIcon = computed<Component>(() => (gateTone.value === 'ok' ? Info : TriangleAlert))
const gateClass = computed(() =>
  gateTone.value === 'ok' ? 'text-ok' : gateTone.value === 'warn' ? 'text-warn' : 'text-info-ink',
)

/** 龙头地图直接给 leaders；龙回头把它嵌在 leader_map 下 */
const leaders = computed(
  () =>
    [
      ...(preview.value?.leaders ?? preview.value?.leader_map?.leaders ?? []),
      ...(preview.value?.weakened ?? preview.value?.leader_map?.weakened ?? []),
    ] as unknown as Record<string, unknown>[],
)

const candidates = computed(() => (preview.value?.picks ?? []) as unknown as Record<string, unknown>[])
const signals = computed(() => (preview.value?.signals ?? []) as unknown as Record<string, unknown>[])
const themes = computed(() => preview.value?.themes ?? [])
const transitions = computed(
  () => (preview.value?.role_transitions ?? []) as unknown as Record<string, unknown>[],
)
const auction = computed(() => preview.value?.auction ?? null)
const auctionStances = computed(
  () => (auction.value?.stances ?? []) as unknown as Record<string, unknown>[],
)

const STANCE_LABEL: Record<string, string> = {
  confirmed: '竞价确认',
  downgraded: '竞价降级',
  abandoned: '竞价放弃',
  pending: '竞价待定',
}

const STANCE_TONE: Record<string, BadgeTone> = {
  confirmed: 'ok',
  downgraded: 'warn',
  abandoned: 'stamp',
  pending: 'info',
}

const skippedReason = computed(() => {
  const data = preview.value
  if (!data?.skipped) return ''
  return data.unavailable_reason || data.reason || '本次扫描已跳过'
})

function signalLabel(type?: string): string {
  return SIGNAL_LABEL[String(type ?? '')] ?? String(type ?? '')
}

function pct(value?: number | null): string {
  return value == null ? '—' : `${value.toFixed(2)}%`
}

const survival = computed(
  () => (roleSummary.value?.leader_survival ?? []) as unknown as Record<string, unknown>[],
)
const warningLead = computed(() => roleSummary.value?.warning_lead ?? null)

const suggestions = computed(() => {
  const fromPreview = preview.value?.suggestions ?? []
  if (fromPreview.length) return fromPreview
  return roleSuggestions.value
})

const leaderColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { slotName: 'role', label: '角色', width: 100 },
  { prop: 'theme_name', label: '题材', minWidth: 110, showOverflowTooltip: true },
  { slotName: 'ladder', label: '连板', width: 70 },
  { slotName: 'gain20', label: '20日', width: 90 },
  { slotName: 'drawdown', label: '回撤', width: 90 },
  { prop: 'role_basis', label: '依据', minWidth: 160, showOverflowTooltip: true },
]

const auctionColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { slotName: 'stance', label: '态度', width: 100 },
  { slotName: 'gap', label: '竞价', width: 90 },
  { prop: 'reason', label: '依据', minWidth: 180, showOverflowTooltip: true },
]

const survivalColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { prop: 'theme_name', label: '题材', minWidth: 110, showOverflowTooltip: true },
  { slotName: 'leaderDays', label: '当龙头', width: 90 },
  { slotName: 'status', label: '现状', minWidth: 110 },
]

const transitionColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { slotName: 'fromTo', label: '演进', width: 150 },
  { prop: 'to_at', label: '发生于', width: 180 },
  { prop: 'basis', label: '依据', minWidth: 160, showOverflowTooltip: true },
]

const candidateColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { prop: 'score', label: '形态分', width: 80 },
  { prop: 'close', label: '参考价', width: 90 },
  { prop: 'thesis', label: '想法', minWidth: 200, showOverflowTooltip: true },
]

const signalColumns: BasicTableColumn[] = [
  { slotName: 'kind', label: '类型', width: 130 },
  { prop: 'code', label: '标的', width: 90 },
  { prop: 'reason', label: '理由', minWidth: 220, showOverflowTooltip: true },
]

async function runPreview(): Promise<void> {
  if (!props.available) return
  running.value = true
  try {
    preview.value = await previewSkillWatch(props.slug)
    if (preview.value?.skipped) toast.warning(skippedReason.value)
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '预览失败'))
    return
  } finally {
    running.value = false
  }
  try {
    // 演进摘要来自累计留痕，是补充信息：读不到不影响本次扫描结果
    const roles = await getLeaderRoles(props.slug)
    roleSummary.value = roles.summary ?? null
    roleSuggestions.value = roles.suggestions ?? []
  } catch {
    roleSummary.value = null
    roleSuggestions.value = []
  }
}
</script>

<template>
  <div class="relative flex min-w-0 flex-col gap-2">
    <PageBusy :busy="running" overlay />
    <!--
      原来这里恒定挂着两条 el-alert：一条报「悟道没装」，一条只是解释「预览是只读的」。
      后者不是异常、永远在，就是被禁的常驻说明条 —— 整条删掉，那句话挂到「立即预览」
      按钮的 tooltip 上。前者留下，但 title 收进 20 字、description 改走 tooltip。
    -->
    <!-- title 直接说后端给的真实原因，不再拆成 title + description 两层 -->
    <Alert v-if="!available" class="mb-2 shrink-0 text-warn">
      <TriangleAlert />
      <AlertTitle class="line-clamp-none min-w-0">{{ unavailableReason || '悟道 MCP 未装配，预览已停用' }}</AlertTitle>
    </Alert>

    <div class="flex flex-wrap items-center gap-2">
      <Tooltip>
        <TooltipTrigger as-child>
          <Button :disabled="!available" @click="runPreview">
            <Spinner v-if="running" class="size-4 animate-spin" aria-hidden="true" />
            立即预览
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="start">
          用实时数据只读试跑一次：不写纸面舱、不推送、不调 AI；结果一律标注未经过前向验证，不构成买卖建议
        </TooltipContent>
      </Tooltip>
      <span v-if="preview?.trade_date" class="text-aux text-mist">交易日 {{ preview.trade_date }}</span>
      <Badge v-if="preview" :class="badgeTone('warn')">
        {{ preview.validation_label || '未经过前向验证' }}
      </Badge>
    </div>

    <EmptyState
      v-if="!preview"
      :description="available ? '还没有预览结果' : '悟道未装配'"
      :reason="available ? '点上方按钮试跑一次' : '装配后才能预览'"
    />

    <template v-else>
      <Alert v-if="suggestions.length" class="mb text-info-ink">
        <Info />
        <AlertTitle class="line-clamp-none min-w-0">调参建议（仅建议，不改参）</AlertTitle>
        <div class="suggestion-list col-start-2">
          <p v-for="(item, index) in suggestions" :key="`${item.direction}-${index}`" class="dim">
            {{ item.message }}
          </p>
        </div>
      </Alert>

      <Alert v-if="skippedReason" class="mb text-warn">
        <TriangleAlert />
        <AlertTitle class="line-clamp-none min-w-0">{{ skippedReason }}</AlertTitle>
      </Alert>

      <!-- 闸门理由是真实判定依据，必须看得见：并进 title，不用 description -->
      <Alert v-if="gate" class="mb" :class="gateClass">
        <component :is="gateIcon" />
        <AlertTitle class="line-clamp-none min-w-0">龙空龙闸门：{{ gate.mode || '观察' }} · {{ gate.label || '' }} · {{ gate.reason || '后端没给理由' }}</AlertTitle>
      </Alert>
      <p v-if="gate?.data_status === 'degraded'" class="dim mb">
        数据不完整，已按空仓处理：{{ (gate.quality_warnings || []).join('、') || '缺少关键指标' }}
      </p>

      <div v-if="themes.length" class="chip-row mb">
        <span class="dim">主线题材</span>
        <Badge
          v-for="theme in themes"
          :key="theme.theme_code || theme.theme_name"
          :class="badgeTone('outline')"
        >
          {{ theme.theme_name }}{{ theme.strength == null ? '' : ` · 强度 ${theme.strength}` }}
        </Badge>
      </div>

      <template v-if="leaders.length">
        <p class="section dim">龙头地图</p>
        <BasicTable
          :columns="leaderColumns"
          :data-source="leaders"
          :pagination="false"
          size="small"
          class="mb"
        >
          <template #role="{ row }">
            <Badge :class="badgeTone(ROLE_TONE[String(row.role)] || 'info')">
              {{ row.role_label || row.role }}
            </Badge>
          </template>
          <template #ladder="{ row }">{{ row.ladder_level ?? '—' }}</template>
          <template #gain20="{ row }">{{ pct(row.gain_20_pct as number | null) }}</template>
          <template #drawdown="{ row }">{{ pct(row.drawdown_pct as number | null) }}</template>
        </BasicTable>
      </template>

      <template v-if="auctionStances.length">
        <p class="section dim">竞价确认</p>
        <BasicTable
          :columns="auctionColumns"
          :data-source="auctionStances"
          :pagination="false"
          size="small"
          class="mb"
        >
          <template #stance="{ row }">
            <Badge :class="badgeTone(STANCE_TONE[String(row.stance)] || 'info')">
              {{ STANCE_LABEL[String(row.stance)] || row.stance }}
            </Badge>
          </template>
          <template #gap="{ row }">{{ pct(row.gap_pct as number | null) }}</template>
        </BasicTable>
      </template>
      <p v-else-if="auction && !auction.active" class="dim mb">
        竞价确认未运行：{{ auction.reason }}
      </p>

      <template v-if="survival.length">
        <p class="section dim">
          龙头存活（累计留痕
          {{ roleSummary?.trade_days ?? 0 }} 个交易日 / {{ roleSummary?.observations ?? 0 }} 次观测）
        </p>
        <BasicTable
          :columns="survivalColumns"
          :data-source="survival"
          :pagination="false"
          size="small"
          class="mb"
        >
          <template #leaderDays="{ row }">{{ row.leader_days }} 日</template>
          <template #status="{ row }">
            <Badge :class="badgeTone(row.still_leader ? 'ok' : ROLE_TONE[String(row.current_role)] || 'info')">
              {{ row.still_leader ? '仍是龙头' : ROLE_LABEL[String(row.current_role)] || row.current_role }}
            </Badge>
          </template>
        </BasicTable>
        <p v-if="warningLead?.samples" class="dim mb">
          走弱预警提前量：{{ warningLead.samples }} 例，平均
          {{ warningLead.avg_days }} 个交易日（{{ warningLead.min_days }}~{{ warningLead.max_days }}）
        </p>
      </template>

      <template v-if="transitions.length">
        <p class="section dim">角色变化（来自留痕）</p>
        <BasicTable
          :columns="transitionColumns"
          :data-source="transitions"
          :pagination="false"
          size="small"
          class="mb"
        >
          <template #fromTo="{ row }">{{ row.from_role }} → {{ row.to_role }}</template>
        </BasicTable>
      </template>

      <template v-if="candidates.length">
        <p class="section dim">纸面候选（未验证）</p>
        <BasicTable
          :columns="candidateColumns"
          :data-source="candidates"
          :pagination="false"
          size="small"
          class="mb"
        />
      </template>

      <template v-if="signals.length">
        <p class="section dim">本次信号</p>
        <BasicTable
          :columns="signalColumns"
          :data-source="signals"
          :pagination="false"
          size="small"
        >
          <template #kind="{ row }">{{ signalLabel(row.type as string) }}</template>
        </BasicTable>
      </template>
    </template>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.75rem;
}
.bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
}
.dim {
  color: var(--mist);
  font-size: 0.76rem;
}
.section {
  margin: 0 0 0.35rem;
}
.chip-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.suggestion-list {
  margin: 0 0 0.35rem;
}
.suggestion-list p {
  margin: 0.15rem 0;
}
</style>
