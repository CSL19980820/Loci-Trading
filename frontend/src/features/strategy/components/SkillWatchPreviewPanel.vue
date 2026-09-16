<script setup lang="ts">
/**
 * 战法监测预览：用实时数据试跑一次确定性扫描。
 *
 * 与定时监测同一套规则，但只读——不落纸面舱、不推送、不调 LLM。
 * 悟道 MCP 未装配时整块置灰，不发请求也不消耗配额。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getLeaderRoles, previewSkillWatch } from '@/shared/api/quant_ops'
import { toErrorMessage } from '@/shared/lib/errors'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { LeaderMapEntry, LeaderRoleSummary, SkillWatchPreview, WatchTuningSuggestion } from '@/shared/types/quant'

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

const ROLE_TYPE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  leader: 'success',
  secondary: 'info',
  follower: 'info',
  weakened: 'warning',
  failed: 'danger',
}

const ROLE_LABEL: Record<string, string> = {
  leader: '龙头',
  secondary: '中军',
  follower: '跟风',
  weakened: '走弱',
  failed: '结构破坏',
}

const gate = computed(() => preview.value?.market_gate ?? null)

const gateType = computed<'success' | 'warning' | 'info'>(() => {
  const state = gate.value?.state
  if (state === 'dragon') return 'success'
  if (state === 'empty') return 'warning'
  return 'info'
})

/** 龙头地图直接给 leaders；龙回头把它嵌在 leader_map 下 */
const leaders = computed<LeaderMapEntry[]>(() => {
  const rows = preview.value?.leaders ?? preview.value?.leader_map?.leaders ?? []
  const weak = preview.value?.weakened ?? preview.value?.leader_map?.weakened ?? []
  return [...rows, ...weak]
})

const candidates = computed(() => preview.value?.picks ?? [])
const signals = computed(() => preview.value?.signals ?? [])
const themes = computed(() => preview.value?.themes ?? [])
const transitions = computed(() => preview.value?.role_transitions ?? [])
const auction = computed(() => preview.value?.auction ?? null)
const auctionStances = computed(() => auction.value?.stances ?? [])

const STANCE_LABEL: Record<string, string> = {
  confirmed: '竞价确认',
  downgraded: '竞价降级',
  abandoned: '竞价放弃',
  pending: '竞价待定',
}

const STANCE_TYPE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  confirmed: 'success',
  downgraded: 'warning',
  abandoned: 'danger',
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

const survival = computed(() => roleSummary.value?.leader_survival ?? [])
const warningLead = computed(() => roleSummary.value?.warning_lead ?? null)

const suggestions = computed(() => {
  const fromPreview = preview.value?.suggestions ?? []
  if (fromPreview.length) return fromPreview
  return roleSuggestions.value
})

async function runPreview(): Promise<void> {
  if (!props.available) return
  running.value = true
  try {
    preview.value = await previewSkillWatch(props.slug)
    if (preview.value?.skipped) ElMessage.warning(skippedReason.value)
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '预览失败'))
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
  <div v-loading="running" class="flex min-w-0 flex-col gap-2">
    <!--
      原来这里恒定挂着两条 el-alert：一条报「悟道没装」，一条只是解释「预览是只读的」。
      后者不是异常、永远在，就是被禁的常驻说明条 —— 整条删掉，那句话挂到「立即预览」
      按钮的 tooltip 上。前者留下，但 title 收进 20 字、description 改走 tooltip。
    -->
    <!-- title 直接说后端给的真实原因，不再拆成 title + description 两层 -->
    <el-alert
      v-if="!available"
      type="warning"
      show-icon
      :closable="false"
      class="mb-2 shrink-0"
      :title="unavailableReason || '悟道 MCP 未装配，预览已停用'"
    />

    <div class="flex flex-wrap items-center gap-2">
      <el-tooltip
        placement="bottom-start"
        content="用实时数据只读试跑一次：不写纸面舱、不推送、不调 AI；结果一律标注未经过前向验证，不构成买卖建议"
      >
        <el-button type="primary" :disabled="!available" :loading="running" @click="runPreview">
          立即预览
        </el-button>
      </el-tooltip>
      <span v-if="preview?.trade_date" class="text-aux text-mist">交易日 {{ preview.trade_date }}</span>
      <UiBadge v-if="preview" variant="warn">
        {{ preview.validation_label || '未经过前向验证' }}
      </UiBadge>
    </div>

    <EmptyState
      v-if="!preview"
      :description="available ? '还没有预览结果' : '悟道未装配'"
      :reason="available ? '点上方按钮试跑一次' : '装配后才能预览'"
    />

    <template v-else>
      <el-alert
        v-if="suggestions.length"
        type="info"
        show-icon
        :closable="false"
        class="mb"
        title="调参建议（仅建议，不改参）"
      >
        <template #default>
          <div class="suggestion-list">
            <p v-for="(item, index) in suggestions" :key="`${item.direction}-${index}`" class="dim">
              {{ item.message }}
            </p>
          </div>
        </template>
      </el-alert>

      <el-alert
        v-if="skippedReason"
        type="warning"
        show-icon
        :closable="false"
        class="mb"
        :title="skippedReason"
      />

      <!-- 闸门理由是真实判定依据，必须看得见：并进 title，不用 description -->
      <el-alert
        v-if="gate"
        class="mb"
        :type="gateType"
        :closable="false"
        show-icon
        :title="`龙空龙闸门：${gate.mode || '观察'} · ${gate.label || ''} · ${gate.reason || '后端没给理由'}`"
      />
      <p v-if="gate?.data_status === 'degraded'" class="dim mb">
        数据不完整，已按空仓处理：{{ (gate.quality_warnings || []).join('、') || '缺少关键指标' }}
      </p>

      <div v-if="themes.length" class="chip-row mb">
        <span class="dim">主线题材</span>
        <el-tag
          v-for="theme in themes"
          :key="theme.theme_code || theme.theme_name"
          size="small"
          effect="plain"
        >
          {{ theme.theme_name }}{{ theme.strength == null ? '' : ` · 强度 ${theme.strength}` }}
        </el-tag>
      </div>

      <template v-if="leaders.length">
        <p class="section dim">龙头地图</p>
        <el-table :data="leaders" size="small" class="mb">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="ROLE_TYPE[String(row.role)] || 'info'" effect="plain">
                {{ row.role_label || row.role }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="theme_name" label="题材" min-width="110" show-overflow-tooltip />
          <el-table-column label="连板" width="70">
            <template #default="{ row }">{{ row.ladder_level ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="20日" width="90">
            <template #default="{ row }">{{ pct(row.gain_20_pct) }}</template>
          </el-table-column>
          <el-table-column label="回撤" width="90">
            <template #default="{ row }">{{ pct(row.drawdown_pct) }}</template>
          </el-table-column>
          <el-table-column prop="role_basis" label="依据" min-width="160" show-overflow-tooltip />
        </el-table>
      </template>

      <template v-if="auctionStances.length">
        <p class="section dim">竞价确认</p>
        <el-table :data="auctionStances" size="small" class="mb">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column label="态度" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="STANCE_TYPE[String(row.stance)] || 'info'" effect="plain">
                {{ STANCE_LABEL[String(row.stance)] || row.stance }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="竞价" width="90">
            <template #default="{ row }">{{ pct(row.gap_pct) }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="依据" min-width="180" show-overflow-tooltip />
        </el-table>
      </template>
      <p v-else-if="auction && !auction.active" class="dim mb">
        竞价确认未运行：{{ auction.reason }}
      </p>

      <template v-if="survival.length">
        <p class="section dim">
          龙头存活（累计留痕
          {{ roleSummary?.trade_days ?? 0 }} 个交易日 / {{ roleSummary?.observations ?? 0 }} 次观测）
        </p>
        <el-table :data="survival" size="small" class="mb">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column prop="theme_name" label="题材" min-width="110" show-overflow-tooltip />
          <el-table-column label="当龙头" width="90">
            <template #default="{ row }">{{ row.leader_days }} 日</template>
          </el-table-column>
          <el-table-column label="现状" min-width="110">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.still_leader ? 'success' : ROLE_TYPE[String(row.current_role)] || 'info'"
                effect="plain"
              >
                {{ row.still_leader ? '仍是龙头' : ROLE_LABEL[String(row.current_role)] || row.current_role }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="warningLead?.samples" class="dim mb">
          走弱预警提前量：{{ warningLead.samples }} 例，平均
          {{ warningLead.avg_days }} 个交易日（{{ warningLead.min_days }}~{{ warningLead.max_days }}）
        </p>
      </template>

      <template v-if="transitions.length">
        <p class="section dim">角色变化（来自留痕）</p>
        <el-table :data="transitions" size="small" class="mb">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column label="演进" width="150">
            <template #default="{ row }">{{ row.from_role }} → {{ row.to_role }}</template>
          </el-table-column>
          <el-table-column prop="to_at" label="发生于" width="180" />
          <el-table-column prop="basis" label="依据" min-width="160" show-overflow-tooltip />
        </el-table>
      </template>

      <template v-if="candidates.length">
        <p class="section dim">纸面候选（未验证）</p>
        <el-table :data="candidates" size="small" class="mb">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column prop="score" label="形态分" width="80" />
          <el-table-column prop="close" label="参考价" width="90" />
          <el-table-column prop="thesis" label="想法" min-width="200" show-overflow-tooltip />
        </el-table>
      </template>

      <template v-if="signals.length">
        <p class="section dim">本次信号</p>
        <el-table :data="signals" size="small">
          <el-table-column label="类型" width="130">
            <template #default="{ row }">{{ signalLabel(row.type) }}</template>
          </el-table-column>
          <el-table-column prop="code" label="标的" width="90" />
          <el-table-column prop="reason" label="理由" min-width="220" show-overflow-tooltip />
        </el-table>
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
