<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Clock, RefreshRight, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  listResearchMembershipSnapshots,
  listResearchPointInTimeFacts,
} from '@/shared/api/quant_research'
import type {
  ResearchMembershipSnapshot,
  ResearchPointInTimeFact,
} from '@/shared/types/quant-research'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import UiCard from '@/shared/components/ui/UiCard.vue'
import UiCardContent from '@/shared/components/ui/UiCardContent.vue'
import UiCardHeader from '@/shared/components/ui/UiCardHeader.vue'
import UiCardTitle from '@/shared/components/ui/UiCardTitle.vue'

import ResearchTemporalImportDialog, { type ResearchTemporalImportKind } from './ResearchTemporalImportDialog.vue'

const props = defineProps<{
  selectedUniverseId?: string
}>()

const emit = defineEmits<{
  'select-universe': [universeId: string]
}>()

const membershipFilter = ref({ universeId: props.selectedUniverseId || '', asOf: '' })
const memberships = ref<ResearchMembershipSnapshot[]>([])
const resolvedMembership = ref<ResearchMembershipSnapshot | null>(null)
const membershipTotal = ref(0)
const membershipLoaded = ref(false)
const membershipLoading = ref(false)
const membershipError = ref('')
const factFilter = ref({ entityId: '', asOf: '', factType: '' as '' | ResearchPointInTimeFact['fact_type'] })
const facts = ref<ResearchPointInTimeFact[]>([])
const selectedFact = ref<ResearchPointInTimeFact | null>(null)
const factTotal = ref(0)
const factLoaded = ref(false)
const factLoading = ref(false)
const factError = ref('')
const importOpen = ref(false)
const importKind = ref<ResearchTemporalImportKind>('membership')
let membershipRequest = 0
let factRequest = 0

const resolvedMembershipLabel = computed(() => {
  const snapshot = resolvedMembership.value
  if (!snapshot) return ''
  return `${snapshot.universe_id} · ${snapshot.as_of} · ${snapshot.available_at} 可见 · ${snapshot.members.length} 个成员`
})

watch(() => props.selectedUniverseId, (value) => {
  const next = String(value || '').trim()
  if (next) membershipFilter.value.universeId = next
})

function sourceText(sourceId: string, revision: string): string {
  return [sourceId, revision].filter(Boolean).join(' · ') || '未提供'
}

function provenanceText(row: Pick<ResearchMembershipSnapshot, 'fetched_at' | 'payload_sha256' | 'parser_revision'> | Pick<ResearchPointInTimeFact, 'fetched_at' | 'payload_sha256' | 'parser_revision'>): string {
  return `${row.fetched_at || '未提供'} · ${row.payload_sha256 || '未提供'} · ${row.parser_revision || '未提供'}`
}

function safeSourceUrl(value: string): string {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : ''
  } catch {
    return ''
  }
}

function membershipType(snapshot: ResearchMembershipSnapshot): 'success' | 'warning' | 'danger' {
  if (!canUseMembership(snapshot)) return 'danger'
  return 'warning'
}

function membershipLabel(snapshot: ResearchMembershipSnapshot): string {
  if (canUseMembership(snapshot)) return 'PIT 可用'
  if (!snapshot.members.length) return '空成员'
  if (!snapshot.available_at) return '缺少可见日'
  if (snapshot.degraded) return '降级'
  if (snapshot.survivorship_bias) return '生存者偏差'
  if (!snapshot.pit_membership) return '非严格 PIT'
  return '不可用于严格 PIT'
}

function canUseMembership(snapshot: ResearchMembershipSnapshot): boolean {
  return Boolean(
    snapshot.available_at
    && snapshot.members.length
    && snapshot.source_id
    && snapshot.source_url
    && snapshot.snapshot_revision
    && snapshot.fetched_at
    && snapshot.payload_sha256
    && snapshot.parser_revision
    && snapshot.pit_membership
    && !snapshot.survivorship_bias
    && !snapshot.degraded,
  )
}

function membershipUnavailableReason(snapshot: ResearchMembershipSnapshot): string {
  if (!snapshot.members.length) return '快照没有真实成员，不能用于严格 PIT'
  if (!snapshot.available_at) return '快照缺少 available_at，不能证明当时可见'
  if (!snapshot.source_id || !snapshot.source_url || !snapshot.snapshot_revision) return '快照缺少来源、链接或版本'
  if (!snapshot.fetched_at || !snapshot.payload_sha256 || !snapshot.parser_revision) {
    return '快照缺少抓取时间、原始载荷 hash 或解析版本，不能作为严格 PIT 证据'
  }
  if (snapshot.degraded || snapshot.survivorship_bias || !snapshot.pit_membership) {
    return snapshot.missing_reason || '快照不是无生存者偏差的 PIT 成员事实'
  }
  return ''
}

function membershipRowKey(row: Record<string, unknown>): string {
  return `${String(row.universe_id ?? '')}:${String(row.as_of ?? '')}:${String(row.snapshot_revision ?? '')}`
}

async function loadMemberships(): Promise<void> {
  const universeId = membershipFilter.value.universeId.trim()
  const asOf = membershipFilter.value.asOf
  if (asOf && !universeId) {
    membershipError.value = '按截止日解析历史股票池时必须填写股票池标识'
    return
  }
  const request = ++membershipRequest
  membershipLoading.value = true
  membershipError.value = ''
  try {
    const response = await listResearchMembershipSnapshots({ universeId: universeId || undefined, asOf: asOf || undefined })
    if (request !== membershipRequest) return
    memberships.value = response.items
    membershipTotal.value = response.total
    resolvedMembership.value = response.resolved ?? null
    membershipLoaded.value = true
  } catch (caught: unknown) {
    if (request === membershipRequest) {
      membershipError.value = caught instanceof Error ? caught.message : '读取历史股票池失败'
    }
  } finally {
    if (request === membershipRequest) membershipLoading.value = false
  }
}

async function loadFacts(): Promise<void> {
  const entityId = factFilter.value.entityId.trim()
  const asOf = factFilter.value.asOf
  if (asOf && !entityId) {
    factError.value = '按截止日解析 PIT 事实时必须填写实体标识'
    return
  }
  const request = ++factRequest
  factLoading.value = true
  factError.value = ''
  try {
    const response = await listResearchPointInTimeFacts({
      entityId: entityId || undefined,
      factType: factFilter.value.factType || undefined,
      asOf: asOf || undefined,
    })
    if (request !== factRequest) return
    facts.value = response.items
    factTotal.value = response.total
    selectedFact.value = response.selected ?? null
    factLoaded.value = true
  } catch (caught: unknown) {
    if (request === factRequest) {
      factError.value = caught instanceof Error ? caught.message : '读取 PIT 事实失败'
    }
  } finally {
    if (request === factRequest) factLoading.value = false
  }
}

function useUniverse(snapshot: ResearchMembershipSnapshot): void {
  if (!canUseMembership(snapshot)) {
    ElMessage.warning(membershipUnavailableReason(snapshot))
    return
  }
  const next = snapshot.universe_id.trim()
  emit('select-universe', next)
  ElMessage.success(`已回填历史股票池标识：${next}`)
}

function openImport(kind: ResearchTemporalImportKind): void {
  importKind.value = kind
  importOpen.value = true
}

function refreshImported(kind: ResearchTemporalImportKind): void {
  if (kind === 'membership') void loadMemberships()
  else void loadFacts()
}

const membershipRows = computed(() => memberships.value as unknown as Record<string, unknown>[])
const factRows = computed(() => facts.value as unknown as Record<string, unknown>[])

const membershipColumns: BasicTableColumn[] = [
  { prop: 'universe_id', label: '股票池', minWidth: 132, showOverflowTooltip: true },
  { prop: 'as_of', label: '快照日', width: 112 },
  { prop: 'available_at', label: '可见日', width: 112 },
  { prop: 'members', label: '成员', width: 78, slotName: 'members' },
  { prop: 'status', label: '状态', width: 108, slotName: 'status' },
  { prop: 'source_id', label: '来源 / 版本', minWidth: 150, showOverflowTooltip: true, slotName: 'source' },
  { prop: 'payload_sha256', label: '抓取 / 载荷 / 解析', minWidth: 240, showOverflowTooltip: true, slotName: 'provenance' },
  { prop: 'universe_id', label: '操作', width: 108, fixed: 'right', slotName: 'actions' },
]

const factColumns: BasicTableColumn[] = [
  { prop: 'observation_id', label: '观察标识', minWidth: 148, showOverflowTooltip: true },
  { prop: 'entity_id', label: '实体', width: 96, showOverflowTooltip: true },
  { prop: 'fact_type', label: '类型', width: 84 },
  { prop: 'observed_on', label: '观察日', width: 112 },
  { prop: 'available_at', label: '可见日', width: 112 },
  { prop: 'source_id', label: '来源 / 版本', minWidth: 150, showOverflowTooltip: true, slotName: 'source' },
  { prop: 'payload_sha256', label: '抓取 / 载荷 / 解析', minWidth: 240, showOverflowTooltip: true, slotName: 'provenance' },
]

defineExpose({ loadMemberships, loadFacts })
</script>

<template>
  <UiCard class="research-surface" aria-label="历史研究数据">
    <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行 -->
    <UiCardHeader>
      <UiCardTitle><el-icon aria-hidden="true"><Clock /></el-icon>历史数据</UiCardTitle>
    </UiCardHeader>
    <UiCardContent :padded="true">

    <section class="temporal-section" aria-label="历史股票池快照">
      <div class="subhead">
        <div><h5>历史股票池快照</h5><span>{{ membershipLoaded ? `${membershipTotal} 条` : '尚未加载' }}</span></div>
        <el-button size="small" :icon="Upload" @click="openImport('membership')">导入快照</el-button>
      </div>
      <el-form class="temporal-query" inline label-position="left" size="small" @submit.prevent="loadMemberships">
        <el-form-item label="股票池标识">
          <el-input v-model="membershipFilter.universeId" clearable maxlength="128" placeholder="例如 CSI300" />
        </el-form-item>
        <el-form-item label="截至日期">
          <el-date-picker v-model="membershipFilter.asOf" value-format="YYYY-MM-DD" type="date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label-width="0">
          <el-button native-type="submit" :icon="RefreshRight" :loading="membershipLoading">读取快照</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="membershipError" class="section-alert" type="error" show-icon :closable="false" :title="membershipError" />
      <div v-if="resolvedMembership" class="resolved-row">
        <el-tag size="small" effect="plain" :type="membershipType(resolvedMembership)">{{ membershipLabel(resolvedMembership) }}</el-tag>
        <span>解析结果</span><code>{{ resolvedMembershipLabel }}</code>
        <span v-if="membershipUnavailableReason(resolvedMembership)">{{ membershipUnavailableReason(resolvedMembership) }}</span>
      </div>
      <BasicTable
        :columns="membershipColumns"
        :data-source="membershipRows"
        :pagination="false"
        :loading="membershipLoading"
        :row-key="membershipRowKey"
        stripe
        :empty-text="membershipLoaded ? '无快照' : '尚未加载'"
        :empty-reason="membershipLoaded ? '换条件，或点「导入快照」' : '先填条件点「读取快照」'"
      >
        <template #members="{ row }">
          {{ Array.isArray(row.members) ? row.members.length : 0 }}
        </template>
        <template #status="{ row }">
          <el-tag size="small" effect="plain" :type="membershipType(row as unknown as ResearchMembershipSnapshot)">{{ membershipLabel(row as unknown as ResearchMembershipSnapshot) }}</el-tag>
        </template>
        <template #source="{ row }">
          <el-link v-if="safeSourceUrl(String(row.source_url || ''))" :href="safeSourceUrl(String(row.source_url || ''))" target="_blank" rel="noopener noreferrer" type="primary">{{ sourceText(String(row.source_id || ''), String(row.snapshot_revision || '')) }}</el-link>
          <span v-else>{{ sourceText(String(row.source_id || ''), String(row.snapshot_revision || '')) }}</span>
        </template>
        <template #provenance="{ row }">
          <code :title="provenanceText(row as unknown as ResearchMembershipSnapshot)">{{ provenanceText(row as unknown as ResearchMembershipSnapshot) }}</code>
        </template>
        <template #actions="{ row }">
          <el-button text size="small" :disabled="!canUseMembership(row as unknown as ResearchMembershipSnapshot)" :title="membershipUnavailableReason(row as unknown as ResearchMembershipSnapshot)" @click="useUniverse(row as unknown as ResearchMembershipSnapshot)">用于严格 PIT</el-button>
        </template>
      </BasicTable>
    </section>

    <section class="temporal-section" aria-label="PIT 事实">
      <div class="subhead">
        <div><h5>PIT 事实</h5><span>{{ factLoaded ? `${factTotal} 条` : '尚未加载' }}</span></div>
        <el-button size="small" :icon="Upload" @click="openImport('fact')">导入事实</el-button>
      </div>
      <el-form class="temporal-query" inline label-position="left" size="small" @submit.prevent="loadFacts">
        <el-form-item label="实体标识">
          <el-input v-model="factFilter.entityId" clearable maxlength="64" placeholder="证券代码或实体 ID" />
        </el-form-item>
        <el-form-item label="事实类型">
          <el-select v-model="factFilter.factType" clearable placeholder="全部" class="fact-type"><el-option label="财务" value="financial" /><el-option label="事件" value="event" /><el-option label="其他" value="other" /></el-select>
        </el-form-item>
        <el-form-item label="截至日期">
          <el-date-picker v-model="factFilter.asOf" value-format="YYYY-MM-DD" type="date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label-width="0">
          <el-button native-type="submit" :icon="RefreshRight" :loading="factLoading">读取事实</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="factError" class="section-alert" type="error" show-icon :closable="false" :title="factError" />
      <div v-if="selectedFact" class="resolved-row">
        <el-tag size="small" effect="plain" type="success">截至日可见</el-tag>
        <span>解析事实</span><code>{{ selectedFact.observation_id }} · {{ selectedFact.available_at }} · {{ selectedFact.revision }}</code>
      </div>
      <BasicTable
        :columns="factColumns"
        :data-source="factRows"
        :pagination="false"
        :loading="factLoading"
        row-key="observation_id"
        stripe
        :empty-text="factLoaded ? '无事实' : '尚未加载'"
        :empty-reason="factLoaded ? '换条件，或点「导入事实」' : '先填条件点「读取事实」'"
      >
        <template #source="{ row }">
          <el-link v-if="safeSourceUrl(String(row.source_url || ''))" :href="safeSourceUrl(String(row.source_url || ''))" target="_blank" rel="noopener noreferrer" type="primary">{{ sourceText(String(row.source_id || ''), String(row.revision || '')) }}</el-link>
          <span v-else>{{ sourceText(String(row.source_id || ''), String(row.revision || '')) }}</span>
        </template>
        <template #provenance="{ row }">
          <code :title="provenanceText(row as unknown as ResearchPointInTimeFact)">{{ provenanceText(row as unknown as ResearchPointInTimeFact) }}</code>
        </template>
      </BasicTable>
    </section>

    <ResearchTemporalImportDialog
      v-model:visible="importOpen"
      :kind="importKind"
      @imported="refreshImported"
    />
    </UiCardContent>
  </UiCard>
</template>

<style scoped>
.temporal-panel { overflow: hidden; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); }
.temporal-head, .subhead { display: flex; align-items: center; justify-content: space-between; gap: var(--gap-3); padding: var(--pad-sheet); }
.temporal-head { border-bottom: 1px solid var(--rule); }
.temporal-head h4, .subhead h5 { margin: 0; color: var(--ink); font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; }
.temporal-section + .temporal-section { border-top: 1px solid var(--rule); }
.subhead { align-items: flex-end; }
.subhead > div { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--gap-1); }
.subhead span { color: var(--mist); font-size: var(--fs-aux); }
/* 筛选条交给 EP inline 表单排版，不再用 grid 覆盖 el-form 布局 */
.temporal-query { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--gap-1) var(--gap-2); padding: 0 var(--pad-sheet-x) var(--gap-2); }
.temporal-query :deep(.el-form-item) { margin: 0; }
.temporal-query :deep(.el-form-item__label) { padding-right: var(--gap-2); }
.fact-type { width: 8rem; }
.section-alert { margin: 0 var(--pad-sheet-x) var(--gap-2); }
.resolved-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-1) var(--gap-2); padding: var(--gap-2) var(--pad-sheet-x); border-top: 1px solid var(--rule); color: var(--mist); font-size: var(--fs-aux); }
code { color: var(--ink); font: var(--fs-aux) var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
@media (max-width: 560px) {
  .temporal-head, .subhead { align-items: flex-start; flex-direction: column; }
  .temporal-query :deep(.el-form-item) { width: 100%; }
}
</style>
<style scoped src="./ResearchSurfaces.css"></style>
