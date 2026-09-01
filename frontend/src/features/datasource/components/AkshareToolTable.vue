<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Sheet from '@/shared/components/layout/Sheet.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import type {
  AkshareBatchProbeItem,
  AkshareCatalog,
  AkshareCatalogCapability,
  AkshareCatalogParameter,
  AkshareCatalogProbeResult,
  AkshareVersionInfo,
  JsonValue,
} from '@/shared/types/quant'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'

import AkshareBatchProbeDialog from './AkshareBatchProbeDialog.vue'

const props = defineProps<{
  catalog: AkshareCatalog | null
  busy: boolean
  probeResult: AkshareCatalogProbeResult | null
  versionInfo?: AkshareVersionInfo | null
  batchOpen: boolean
  batchProgress: { done: number; total: number; ok: number; failed: number; skipped: number }
  batchResults: AkshareBatchProbeItem[]
  /** 从数据源卡片跳进来时预选的来源（英文 id） */
  source?: string
}>()

const emit = defineEmits<{
  probe: [payload: { name: string; params: Record<string, unknown> }]
  'probe-all': []
  'stop-batch': []
  'check-version': []
  'update:batchOpen': [open: boolean]
}>()

const query = ref('')
const category = ref('')
const provider = ref(props.source ?? '')
const health = ref<'' | 'ok' | 'fail' | 'untested'>('')
const visible = ref(false)
const selected = ref<AkshareCatalogCapability | null>(null)
const params = ref<Record<string, unknown>>({})
const parameterErrors = ref<Record<string, string>>({})
const lastProbeName = ref<string | null>(null)

const capabilities = computed(() => props.catalog?.capabilities ?? [])
const categoryOptions = computed(() => {
  const map = new Map<string, string>()
  for (const item of capabilities.value) {
    map.set(item.category, item.category_label || item.category)
  }
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1], 'zh'))
})
const providerOptions = computed(() => {
  const map = new Map<string, string>()
  for (const item of capabilities.value) {
    const id = item.provider_id || item.provider
    map.set(id, item.provider)
  }
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1], 'zh'))
})

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return capabilities.value.filter((item) => {
    if (keyword && !`${item.name} ${item.summary}`.toLowerCase().includes(keyword)) return false
    if (category.value && item.category !== category.value) return false
    const providerId = item.provider_id || item.provider
    if (provider.value && providerId !== provider.value && item.provider !== provider.value) return false
    if (health.value === 'ok' && item.health_ok !== true) return false
    if (health.value === 'fail' && item.health_ok !== false) return false
    if (health.value === 'untested' && item.health_ok != null) return false
    return true
  })
})

const page = ref(1)
const pageSize = ref(25)

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const tableRows = computed(() => paged.value as unknown as Record<string, unknown>[])

const columns = ref<BasicTableColumn[]>([
  { prop: 'name', label: '接口', minWidth: 190, align: 'center', headerAlign: 'center', showOverflowTooltip: true },
  { prop: 'category_label', label: '类目', width: 110, align: 'center', headerAlign: 'center', slotName: 'category' },
  { prop: 'provider', label: '来源', width: 110, align: 'center', headerAlign: 'center' },
  { prop: 'summary', label: '说明', minWidth: 200, align: 'left', headerAlign: 'left', showOverflowTooltip: true },
  { prop: 'status', label: '就绪', width: 100, align: 'center', headerAlign: 'center', slotName: 'ready' },
  { prop: 'health_ok', label: '探测', width: 88, align: 'center', headerAlign: 'center', slotName: 'health' },
  { prop: 'health_elapsed_ms', label: '响应', width: 92, align: 'center', headerAlign: 'center', slotName: 'rtt' },
  { prop: 'actions', label: '操作', width: 88, fixed: 'right', align: 'center', headerAlign: 'center', slotName: 'actions' },
])

const pager = computed(() => ({
  pageSize: pageSize.value,
  currentPage: page.value,
  total: filtered.value.length,
  pageSizes: [25, 50, 100],
  layout: 'total, sizes, prev, pager, next',
}))

const selectedProbeResult = computed(() =>
  selected.value?.name === lastProbeName.value ? props.probeResult : null,
)
const sampleColumns = computed(() => {
  const result = selectedProbeResult.value
  if (!result) return []
  return result.columns?.length ? result.columns : [...new Set((result.sample ?? []).flatMap((row) => Object.keys(row)))]
})
const versionChip = computed(() => {
  const info = props.versionInfo
  if (info?.update_available) return `可升级 ${info.latest}`
  return props.catalog?.akshare_version || '未加载'
})
const batchOpenModel = computed({
  get: () => props.batchOpen,
  set: (value: boolean) => emit('update:batchOpen', value),
})

function openProbe(item: AkshareCatalogCapability): void {
  selected.value = item
  params.value = Object.fromEntries(item.parameters.map((parameter) => [parameter.name, initialValue(parameter)]))
  parameterErrors.value = {}
  visible.value = true
}

function initialValue(parameter: AkshareCatalogParameter): JsonValue | '' {
  const value = parameter.sample != null
    ? parameter.sample
    : parameter.has_default
      ? parameter.default
      : ''
  const kind = inputKind(parameter)
  if (kind === 'number') {
    if (value === '' || value == null) return null
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : value
  }
  if (kind === 'boolean') {
    if (typeof value === 'boolean') return value
    if (typeof value === 'string') return value.trim().toLowerCase() === 'true'
    return Boolean(value)
  }
  return value
}

function inputKind(parameter: AkshareCatalogParameter): 'boolean' | 'number' | 'text' {
  const annotation = parameter.annotation?.toLowerCase() ?? ''
  if (/(^|[^a-z_])bool(?:ean)?([^a-z_]|$)/.test(annotation)) return 'boolean'
  if (/(^|[^a-z_])(int(?:eger)?|float|number|decimal)([^a-z_]|$)/.test(annotation)) return 'number'
  return 'text'
}

function isMissing(value: unknown): boolean {
  if (value == null) return true
  if (typeof value === 'string') return !value.trim()
  if (typeof value === 'number') return !Number.isFinite(value)
  return Array.isArray(value) && !value.length
}

function validateParameters(item: AkshareCatalogCapability): boolean {
  const errors: Record<string, string> = {}
  for (const parameter of item.parameters) {
    if (parameter.required && isMissing(params.value[parameter.name])) {
      errors[parameter.name] = `请填写必填参数「${parameter.name}」。`
    }
  }
  parameterErrors.value = errors
  return !Object.keys(errors).length
}

function submitProbe(): void {
  const item = selected.value
  if (!item || !capabilities.value.some((candidate) => candidate.name === item.name)) return
  if (!validateParameters(item)) return
  lastProbeName.value = item.name
  const probeParams = Object.fromEntries(
    item.parameters.flatMap((parameter) => {
      const value = params.value[parameter.name]
      return !parameter.required && isMissing(value) ? [] : [[parameter.name, value]]
    }),
  )
  emit('probe', { name: item.name, params: probeParams })
}

function healthTag(item: Record<string, unknown>): { type: 'success' | 'danger' | 'info'; label: string } {
  if (item.health_ok === true) return { type: 'success', label: '通' }
  if (item.health_ok === false) return { type: 'danger', label: '败' }
  return { type: 'info', label: '未测' }
}

function categoryText(row: Record<string, unknown>): string {
  return String(row.category_label || row.category || '—')
}

watch([query, category, provider, health, pageSize], () => { page.value = 1 })
watch(() => props.source, (next) => { provider.value = next ?? '' })
watch(filtered, () => {
  const lastPage = Math.max(1, Math.ceil(filtered.value.length / pageSize.value) || 1)
  if (page.value > lastPage) page.value = lastPage
})
</script>

<template>
  <!--
    「接口」标题删了：表头已写「接口 / 说明 / 入参」，视图切换器也写着「按接口」，
    本视图内没有并列兄弟块要区分。版本 chip 迁到本块第一条功能行（头部读数），信息不丢。
  -->
  <Sheet class="ak-sheet" plain>
    <template #header>
      <HeaderStat label="AkShare 版本" :value="versionChip" />
    </template>

    <template #actions>
      <el-button type="primary" size="small" :loading="busy" @click="emit('probe-all')">一键全测</el-button>
      <el-button size="small" :disabled="!busy" @click="emit('stop-batch')">停止</el-button>
      <el-button size="small" :loading="busy" @click="emit('check-version')">检查版本更新</el-button>
      <span v-if="versionInfo?.update_available" class="version-hint">
        {{ versionInfo.installed }} → {{ versionInfo.latest }}
      </span>
    </template>

    <div class="ak-panel">
      <div class="catalog-filters">
        <el-input v-model="query" clearable placeholder="按接口名或说明筛选" aria-label="接口名筛选" />
        <el-select v-model="category" clearable placeholder="类目" aria-label="类目筛选">
          <el-option
            v-for="[value, label] in categoryOptions"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="provider" clearable placeholder="来源" aria-label="来源筛选">
          <el-option
            v-for="[value, label] in providerOptions"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="health" clearable placeholder="探测结果" aria-label="探测结果筛选">
          <el-option value="ok" label="已通过" />
          <el-option value="fail" label="失败" />
          <el-option value="untested" label="未测" />
        </el-select>
      </div>

      <div v-if="catalog" class="ak-table-wrap">
        <BasicTable
          v-model:columns="columns"
          :data-source="tableRows"
          :loading="busy && !capabilities.length"
          :pagination="pager"
          :toolbar-config="{ refresh: false, custom: true }"
          row-key="name"
          stripe
          empty-text="没有匹配的接口"
          class="ak-table"
          @current-change="(p) => { page = p }"
          @size-change="(s) => { pageSize = s; page = 1 }"
        >
          <template #toolbarButtons>
            <span class="filter-meta">筛选 {{ filtered.length }} / 目录 {{ capabilities.length }}</span>
          </template>
          <template #category="{ row }">{{ categoryText(row) }}</template>
          <template #ready="{ row }">
            <el-tag size="small" :type="row.status === 'available' ? 'success' : 'warning'">
              {{ row.status === 'available' ? '可试跑' : '需填写参数' }}
            </el-tag>
          </template>
          <template #health="{ row }">
            <el-tooltip
              :content="String(row.health_error || (row.health_elapsed_ms != null ? `${row.health_elapsed_ms} ms` : '尚未探测'))"
              placement="top"
            >
              <el-tag size="small" :type="healthTag(row).type">{{ healthTag(row).label }}</el-tag>
            </el-tooltip>
          </template>
          <template #rtt="{ row }">
            <span class="mono">
              {{ row.health_elapsed_ms == null ? '—' : `${Math.round(Number(row.health_elapsed_ms))} ms` }}
            </span>
          </template>
          <template #actions="{ row }">
            <el-button size="small" link type="primary" @click="openProbe(row as unknown as AkshareCatalogCapability)">
              试跑
            </el-button>
          </template>
        </BasicTable>
      </div>
      <EmptyState v-else description="接口目录尚未加载" reason="点右上「刷新」重读一次" />
    </div>
  </Sheet>

  <AkshareBatchProbeDialog
    v-model="batchOpenModel"
    :busy="busy"
    :progress="batchProgress"
    :results="batchResults"
    @stop="emit('stop-batch')"
  />

  <el-dialog v-model="visible" :title="selected ? `试跑 ${selected.name}` : '接口试跑'" width="720px" destroy-on-close>
    <p v-if="selected" class="signature">{{ selected.signature }} · {{ selected.summary }}</p>
    <el-form label-position="right" label-width="6.5em" size="small" class="params-form" @submit.prevent="submitProbe">
      <el-form-item
        v-for="parameter in selected?.parameters ?? []"
        :key="parameter.name"
        :label="parameter.name"
        :required="parameter.required"
        :error="parameterErrors[parameter.name]"
      >
        <el-switch
          v-if="inputKind(parameter) === 'boolean'"
          v-model="params[parameter.name]"
          :aria-invalid="Boolean(parameterErrors[parameter.name])"
        />
        <el-input-number
          v-else-if="inputKind(parameter) === 'number'"
          v-model="params[parameter.name]"
          controls-position="right"
          :aria-invalid="Boolean(parameterErrors[parameter.name])"
        />
        <el-input
          v-else
          v-model="params[parameter.name]"
          :aria-invalid="Boolean(parameterErrors[parameter.name])"
          :aria-label="parameter.name"
        />
        <p class="parameter-meta">
          {{ parameter.kind }}<span v-if="parameter.annotation"> · {{ parameter.annotation }}</span>
          <span v-if="parameter.has_default"> · 默认：{{ String(parameter.default) }}</span>
          <span v-if="parameter.sample != null && parameter.sample !== parameter.default"> · 测试值：{{ String(parameter.sample) }}</span>
          <span v-else-if="parameter.sample != null"> · 示例：{{ String(parameter.sample) }}</span>
        </p>
      </el-form-item>
    </el-form>
    <el-alert
      v-if="Object.keys(parameterErrors).length"
      :title="Object.values(parameterErrors).join(' ')"
      type="error"
      show-icon
      :closable="false"
    />
    <el-alert v-if="selectedProbeResult?.error" :title="selectedProbeResult.error" type="error" show-icon :closable="false" />
    <div v-else-if="selectedProbeResult" class="probe-summary">
      RTT：{{ selectedProbeResult.elapsed_ms ?? '—' }} ms；行数：{{ selectedProbeResult.rows ?? '—' }}；列数：{{ sampleColumns.length }}
      <span v-if="selectedProbeResult.truncated">；样本已截断</span>
    </div>
    <el-table v-if="selectedProbeResult?.sample?.length" :data="selectedProbeResult.sample" size="small" max-height="240">
      <el-table-column v-for="column in sampleColumns" :key="column" :prop="column" :label="column" min-width="120" show-overflow-tooltip />
    </el-table>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :loading="busy" :disabled="!selected" @click="submitProbe">执行试跑</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.ak-sheet {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
}
/* 只在 sheet 内层做一次 flex 传递：不再逐层写 height:100% 互相打架 */
.ak-sheet :deep(.sheet-slot) {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
}
.ak-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  gap: var(--gap-2);
}
.version-hint { color: var(--warn); font-size: var(--fs-aux); }
.catalog-filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--gap-2);
  flex-shrink: 0;
}
/* 高度内容驱动：表体自己吃满剩余空间，空目录时不留 12rem 死白 */
.ak-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.filter-meta { color: var(--mist); font-size: var(--fs-aux); }
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.signature { margin: 0 0 var(--gap-2); color: var(--mist); font-family: var(--mono); font-size: var(--fs-aux); overflow-wrap: anywhere; }
/* 表单栅格挂在 el-form 自身：不插裸 div，label 宽仍由 EP 的 label-width 算 */
.params-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--gap-1) var(--gap-3);
  align-items: start;
}
.params-form :deep(.el-form-item) { margin-bottom: var(--gap-1); min-width: 0; }
.parameter-meta { margin: 2px 0 0; color: var(--mist); font-size: var(--fs-kicker); line-height: 1.35; }
.probe-summary { margin: var(--gap-2) 0; color: var(--mist); font-size: var(--fs-aux); font-variant-numeric: tabular-nums; }
</style>
