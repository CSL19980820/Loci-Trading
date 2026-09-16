<script setup lang="ts">
import { computed } from 'vue'
import { Link } from '@element-plus/icons-vue'

import type { ResearchProfile, ResearchQualitySnapshot, ResearchRun } from '@/shared/types/quant'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import UiCard from '@/shared/components/ui/UiCard.vue'
import UiCardHeader from '@/shared/components/ui/UiCardHeader.vue'
import UiCardTitle from '@/shared/components/ui/UiCardTitle.vue'

const props = defineProps<{
  profile: ResearchProfile
  run: ResearchRun | null
}>()

const quality = computed<ResearchQualitySnapshot>(() => props.profile.quality)
const evidence = computed(() => props.profile.dimensions.flatMap((dimension) =>
  dimension.evidence.map((item) => ({ ...item, dimension: dimension.name })),
))
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

const findingRows = computed(() => quality.value.findings as unknown as Record<string, unknown>[])
const evidenceRows = computed(() => evidence.value as unknown as Record<string, unknown>[])

const findingColumns: BasicTableColumn[] = [
  { prop: 'severity', label: '级别', width: 84, slotName: 'severity' },
  { prop: 'code', label: '规则', width: 170, showOverflowTooltip: true },
  { prop: 'message', label: '事实', minWidth: 240, showOverflowTooltip: true },
  { prop: 'suggested_fix', label: '缺口处理', minWidth: 190, showOverflowTooltip: true },
]

const evidenceColumns: BasicTableColumn[] = [
  { prop: 'dimension', label: '维度', width: 120, showOverflowTooltip: true },
  { prop: 'source_id', label: '来源', width: 120 },
  { prop: 'as_of', label: '截止日', width: 112 },
  { prop: 'payload_sha256', label: 'hash / 链接', minWidth: 230, slotName: 'hash' },
]
</script>

<template>
  <UiCard class="research-surface" aria-label="证据与风险透视">
    <UiCardHeader>
      <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行 -->
      <UiCardTitle><el-icon aria-hidden="true"><Link /></el-icon>证据与风险透视</UiCardTitle>
      <template #action>
        <UiBadge :variant="quality.blocked ? 'stamp' : 'ok'">
          {{ quality.blocked ? '已阻断' : '可查看' }}
        </UiBadge>
      </template>
    </UiCardHeader>
    <div v-if="riskItems.length" class="border-line grid grid-cols-[repeat(auto-fit,minmax(min(100%,200px),1fr))] gap-px border-b bg-[var(--rule)]">
      <div v-for="item in riskItems" :key="item.key" class="bg-surface min-w-0 px-3 py-2">
        <span class="text-aux text-mist block">{{ item.label }}</span>
        <strong class="text-body text-ink mt-1 block font-mono leading-snug font-bold break-all tabular-nums">{{ item.value }}</strong>
      </div>
    </div>
    <div v-if="snapshotEntries.length" class="border-line text-aux text-mist flex flex-wrap gap-x-3 gap-y-1 border-b px-[var(--pad-sheet-x)] py-[var(--pad-sheet-y)]">
      <span class="text-mist basis-full">行情快照</span>
      <span v-for="[key, value] in snapshotEntries" :key="key" class="max-w-full break-all"><code class="font-mono tabular-nums">{{ key }}</code> {{ value }}</span>
    </div>
    <div v-if="healthEntries.length" class="border-line text-aux text-mist flex flex-wrap gap-x-3 gap-y-1 border-b px-[var(--pad-sheet-x)] py-[var(--pad-sheet-y)]">
      <span class="text-mist basis-full">行情健康事实</span>
      <span v-for="[key, value] in healthEntries" :key="key"><code class="font-mono tabular-nums">{{ key }}</code> {{ String(value) }}</span>
    </div>
    <BasicTable
      :columns="findingColumns"
      :data-source="findingRows"
      :pagination="false"
      stripe
      empty-text="没有验证问题"
      empty-reason=""
    >
      <template #severity="{ row }">
        <UiBadge :variant="row.severity === 'critical' ? 'stamp' : row.severity === 'warning' ? 'warn' : 'info'">{{ row.severity }}</UiBadge>
      </template>
    </BasicTable>
    <div class="border-line text-aux text-mist flex justify-between gap-3 border-t px-[var(--pad-sheet-x)] pt-2 pb-1"><span>来源证据 · {{ evidence.length }}</span><span v-if="props.run">run {{ props.run.id }}</span></div>
    <BasicTable
      :columns="evidenceColumns"
      :data-source="evidenceRows"
      :pagination="false"
      stripe
      empty-text="没有来源证据"
      empty-reason="读取剖面后由后端回执填入"
    >
      <template #hash="{ row }">
        <el-link v-if="row.source_url" :href="String(row.source_url)" target="_blank" rel="noopener noreferrer" :icon="Link">{{ row.title || row.source_id }}</el-link>
        <code v-else :title="String(row.payload_sha256 || '')">{{ row.payload_sha256 || '无 hash' }}</code>
      </template>
    </BasicTable>
  </UiCard>
</template>

<style scoped>
/* 皮肤已上移到 UiCard + 工具类；el-table 穿透与 code 等宽保留 */
.health-item code, code { font-family: var(--mono); font-size: var(--fs-aux); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
</style>
<style scoped src="./ResearchSurfaces.css"></style>
