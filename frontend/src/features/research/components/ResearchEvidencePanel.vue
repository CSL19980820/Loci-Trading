<script setup lang="ts">
import { computed } from 'vue'
import { Link } from '@element-plus/icons-vue'

import type { ResearchProfile, ResearchQualitySnapshot, ResearchRun } from '@/shared/types/quant'

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
  return '未在当前 profile 契约提供'
})
</script>

<template>
  <section class="evidence-panel" aria-label="证据与风险透视">
    <header class="section-head">
      <div><span class="research-kicker">REVIEW & RISK</span><h3>证据与风险透视</h3></div>
      <el-tag size="small" effect="plain" :type="quality.blocked ? 'danger' : 'success'">
        {{ quality.blocked ? 'blocked' : '可查看' }}
      </el-tag>
    </header>
    <div class="risk-grid">
      <div><span>PIT / 生存者偏差</span><strong>{{ pitLabel }}</strong></div>
      <div><span>验证失败 / 门禁</span><strong>{{ quality.findings.length ? `${quality.findings.length} 项` : '未发现' }}</strong></div>
      <div><span>风险透视</span><strong>未在当前 profile 契约提供</strong></div>
      <div><span>行情快照</span><strong>{{ props.profile.market_snapshot.market_revision || quality.market_revision || '—' }}</strong></div>
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
    <el-empty v-else description="当前没有验证问题" :image-size="48" />
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
    <el-empty v-else description="当前没有来源证据" :image-size="48" />
  </section>
</template>

<style scoped>
.evidence-panel { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); overflow: hidden; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.75rem; padding: 0.82rem 0.9rem; border-bottom: 1px solid var(--rule); }
.section-head h3 { margin: 0.22rem 0 0; font-size: 0.98rem; letter-spacing: 0; }
.research-kicker { display: block; color: var(--mist); font: 0.68rem/1.2 var(--mono); letter-spacing: 0.08em; }
.risk-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--rule); border-bottom: 1px solid var(--rule); }
.risk-grid > div { min-width: 0; padding: 0.68rem 0.72rem; background: var(--sheet); }
.risk-grid span, .subhead { display: block; color: var(--mist); font-size: 0.72rem; }
.risk-grid strong { display: block; margin-top: 0.25rem; color: var(--ink); font: 600 0.8rem/1.3 var(--mono); overflow-wrap: anywhere; }
.health-list { display: flex; flex-wrap: wrap; gap: 0.35rem 0.75rem; padding: 0.65rem 0.9rem; border-bottom: 1px solid var(--rule); color: var(--mist); font-size: 0.74rem; }
.health-list .subhead { flex-basis: 100%; }
.snapshot-list { display: flex; flex-wrap: wrap; gap: 0.35rem 0.75rem; padding: 0.65rem 0.9rem; border-bottom: 1px solid var(--rule); color: var(--mist); font-size: 0.74rem; }
.snapshot-list .subhead { flex-basis: 100%; }
.snapshot-item { max-width: 100%; overflow-wrap: anywhere; }
.health-item code, code { font-family: var(--mono); font-size: 0.72rem; overflow-wrap: anywhere; }
.finding-table { width: 100%; }
.evidence-head { display: flex; justify-content: space-between; gap: 0.75rem; padding: 0.7rem 0.9rem 0.4rem; border-top: 1px solid var(--rule); color: var(--mist); font-size: 0.72rem; }
@media (max-width: 900px) { .risk-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .risk-grid { grid-template-columns: 1fr; } }
</style>
