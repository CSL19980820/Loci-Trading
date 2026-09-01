<script setup lang="ts">
import { computed } from 'vue'
import { Link } from '@element-plus/icons-vue'

import type { ResearchProfile, ResearchQualitySnapshot, ResearchRun } from '@/shared/types/quant'

import EmptyState from '@/shared/components/ui/EmptyState.vue'

const props = defineProps<{
  profile: ResearchProfile
  run: ResearchRun | null
}>()

const quality = computed<ResearchQualitySnapshot>(() => props.profile.quality)
const evidence = computed(() => props.profile.dimensions.flatMap((dimension) =>
  dimension.evidence.map((item) => ({ ...item, dimension: dimension.name })),
))
const findingType = (severity: 'critical' | 'warning' | 'info'): 'danger' | 'warning' | 'info' =>
  severity === 'critical' ? 'danger' : severity === 'warning' ? 'warning' : 'info'
const healthEntries = computed(() => Object.entries(quality.value.market_health || {}).filter(([, value]) => value !== null && value !== undefined && value !== ''))
const snapshotEntries = computed(() => Object.entries(props.profile.market_snapshot || {})
  .filter(([, value]) => value !== null && value !== undefined && value !== '')
  .map(([key, value]) => [key, typeof value === 'object' ? JSON.stringify(value) : String(value)] as const)
  .slice(0, 8))
const pitLabel = computed(() => {
  const health = quality.value.market_health || {}
  if ('pit_degraded' in health) return health.pit_degraded ? '降级' : '已提供'
  if ('survivorship_bias' in health) return health.survivorship_bias ? '存在风险' : '未发现'
  return ''
})
/**
 * 「字段缺失保持空缺不补零」= 整项不渲染，而不是留一个空格子。
 * 后端没给的口径（例如 profile 契约里根本没有的风险透视）直接不进列表。
 */
const riskItems = computed(() => [
  { key: 'pit', label: 'PIT / 生存者偏差', value: pitLabel.value },
  { key: 'gate', label: '验证失败 / 门禁', value: quality.value.findings.length ? `${quality.value.findings.length} 项` : '未发现' },
  { key: 'revision', label: '行情快照', value: String(props.profile.market_snapshot.market_revision || quality.value.market_revision || '') },
].filter((item) => item.value))
</script>

<template>
  <section class="evidence-panel" aria-label="证据与风险透视">
    <header class="section-head">
      <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
      <h3>证据与风险透视</h3>
      <el-tag size="small" effect="plain" :type="quality.blocked ? 'danger' : 'success'">
        {{ quality.blocked ? 'blocked' : '可查看' }}
      </el-tag>
    </header>
    <div v-if="riskItems.length" class="risk-grid">
      <div v-for="item in riskItems" :key="item.key"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
    </div>
    <div v-if="snapshotEntries.length" class="snapshot-list">
      <span class="subhead">MARKET SNAPSHOT</span>
      <span v-for="[key, value] in snapshotEntries" :key="key" class="snapshot-item"><code>{{ key }}</code> {{ value }}</span>
    </div>
    <div v-if="healthEntries.length" class="health-list">
      <span class="subhead">行情健康事实</span>
      <span v-for="[key, value] in healthEntries" :key="key" class="health-item"><code>{{ key }}</code> {{ String(value) }}</span>
    </div>
    <el-table v-if="quality.findings.length" :data="quality.findings" size="small" class="finding-table">
      <el-table-column label="级别" width="84"><template #default="{ row }"><el-tag size="small" effect="plain" :type="findingType(row.severity)">{{ row.severity }}</el-tag></template></el-table-column>
      <el-table-column prop="code" label="规则" width="170" show-overflow-tooltip />
      <el-table-column prop="message" label="事实" min-width="240" show-overflow-tooltip />
      <el-table-column prop="suggested_fix" label="缺口处理" min-width="190" show-overflow-tooltip />
    </el-table>
    <EmptyState v-else description="没有验证问题" reason="门禁通过，无需处理" />
    <div class="evidence-head"><span class="subhead">SOURCE EVIDENCE · {{ evidence.length }}</span><span v-if="props.run">run {{ props.run.id }}</span></div>
    <el-table v-if="evidence.length" :data="evidence" size="small" class="finding-table">
      <el-table-column prop="dimension" label="维度" width="120" show-overflow-tooltip />
      <el-table-column prop="source_id" label="来源" width="120" />
      <el-table-column prop="as_of" label="截止日" width="112" />
      <el-table-column label="hash / 链接" min-width="230">
        <template #default="{ row }">
          <el-link v-if="row.source_url" :href="row.source_url" target="_blank" rel="noopener noreferrer" :icon="Link">{{ row.title || row.source_id }}</el-link>
          <code v-else :title="row.payload_sha256">{{ row.payload_sha256 || '无 hash' }}</code>
        </template>
</el-table-column>
</el-table>
<EmptyState v-else description="没有来源证据" reason="读取剖面后由后端回执填入" />
</section>
</template>

<style scoped>
.evidence-panel { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); overflow: hidden; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gap-3); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.section-head h3 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; }
.risk-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1px; background: var(--rule); border-bottom: 1px solid var(--rule); }
.risk-grid > div { min-width: 0; padding: var(--gap-2) var(--gap-3); background: var(--sheet); }
.risk-grid span, .subhead { display: block; color: var(--mist); font-size: var(--fs-aux); }
.risk-grid strong { display: block; margin-top: var(--gap-1); color: var(--ink); font: 700 var(--fs-body)/1.3 var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.health-list, .snapshot-list { display: flex; flex-wrap: wrap; gap: var(--gap-1) var(--gap-3); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); color: var(--mist); font-size: var(--fs-aux); }
.health-list .subhead, .snapshot-list .subhead { flex-basis: 100%; }
.snapshot-item { max-width: 100%; overflow-wrap: anywhere; }
.health-item code, code { font-family: var(--mono); font-size: var(--fs-aux); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.finding-table { width: 100%; }
.evidence-head { display: flex; justify-content: space-between; gap: var(--gap-3); padding: var(--gap-2) var(--pad-sheet-x) var(--gap-1); border-top: 1px solid var(--rule); color: var(--mist); font-size: var(--fs-aux); }
</style>
