<script setup lang="ts">
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { computed, ref, watch } from 'vue'
import { LoaderCircle, X } from '@lucide/vue'

import Sheet from '@/shared/components/layout/Sheet.vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Badge } from '@/shared/components/ui/badge'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
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

/** shadcn Select 没有清除按钮，用一个「全部」哨兵项顶替原 el-select 的 clearable */
const ALL = '__all__'


const TAG_TONE: Record<'success' | 'warning' | 'info' | 'danger', string> = {
  success: 'border-transparent bg-ok-soft text-ok',
  warning: 'border-transparent bg-warn-soft text-warn-ink',
  info: 'border-line bg-sunken text-mist',
  danger: 'text-stamp border-[color-mix(in_oklab,var(--stamp)_38%,var(--rule))] bg-surface',
}

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

/** 三个筛选器：空串仍表示「不筛」，Select 里用哨兵项映射回来 */
const categoryModel = computed({
  get: () => category.value || ALL,
  set: (next: string) => { category.value = next === ALL ? '' : next },
})
const providerModel = computed({
  get: () => provider.value || ALL,
  set: (next: string) => { provider.value = next === ALL ? '' : next },
})
const healthModel = computed({
  get: () => health.value || ALL,
  set: (next: string) => { health.value = next === ALL ? '' : (next as typeof health.value) },
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
  { prop: 'summary', label: '说明', minWidth: 200, align: 'center', headerAlign: 'center', showOverflowTooltip: true },
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
/** 探测样本表：列由后端返回的字段名动态生成 */
const sampleTableColumns = computed<BasicTableColumn[]>(() =>
  sampleColumns.value.map((column) => ({
    prop: column,
    label: column,
    minWidth: 120,
    showOverflowTooltip: true,
  })),
)
const sampleRows = computed(
  () => (selectedProbeResult.value?.sample ?? []) as unknown as Record<string, unknown>[],
)
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

/** 控件都是受控绑定：入参表是 Record<string, unknown>，取值处显式收窄类型 */
function textParam(name: string): string {
  const value = params.value[name]
  return value == null ? '' : String(value)
}

function numberParam(name: string): number | null {
  const value = params.value[name]
  if (value == null || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function boolParam(name: string): boolean {
  return params.value[name] === true
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

function healthTag(item: Record<string, unknown>): { tone: string; label: string } {
  if (item.health_ok === true) return { tone: TAG_TONE.success, label: '通' }
  if (item.health_ok === false) return { tone: TAG_TONE.danger, label: '败' }
  return { tone: TAG_TONE.info, label: '未测' }
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
      <Button size="sm" :disabled="busy" @click="emit('probe-all')">
        <LoaderCircle v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
        一键全测
      </Button>
      <Button size="sm" variant="outline" :disabled="!busy" @click="emit('stop-batch')">
        <X class="size-4" aria-hidden="true" />
        停止
      </Button>
      <Button size="sm" variant="outline" :disabled="busy" @click="emit('check-version')">
        <LoaderCircle v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
        检查版本更新
      </Button>
      <span v-if="versionInfo?.update_available" class="version-hint">
        {{ versionInfo.installed }} → {{ versionInfo.latest }}
      </span>
    </template>

    <div class="ak-panel flex min-h-0 min-w-0 flex-1 flex-col">
      <div class="catalog-filters grid shrink-0">
        <Input v-model="query" placeholder="按接口名或说明筛选" aria-label="接口名筛选" />
        <Select v-model="categoryModel">
          <SelectTrigger class="w-full" aria-label="类目筛选">
            <SelectValue placeholder="类目" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="ALL">全部类目</SelectItem>
            <SelectItem v-for="[value, label] in categoryOptions" :key="value" :value="value">
              {{ label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="providerModel">
          <SelectTrigger class="w-full" aria-label="来源筛选">
            <SelectValue placeholder="来源" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="ALL">全部来源</SelectItem>
            <SelectItem v-for="[value, label] in providerOptions" :key="value" :value="value">
              {{ label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="healthModel">
          <SelectTrigger class="w-full" aria-label="探测结果筛选">
            <SelectValue placeholder="探测结果" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="ALL">全部结果</SelectItem>
            <SelectItem value="ok">已通过</SelectItem>
            <SelectItem value="fail">失败</SelectItem>
            <SelectItem value="untested">未测</SelectItem>
          </SelectContent>
        </Select>
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
            <Badge
              variant="outline"
              :class="row.status === 'available' ? TAG_TONE.success : TAG_TONE.warning"
            >
              {{ row.status === 'available' ? '可试跑' : '需填写参数' }}
            </Badge>
          </template>
          <template #health="{ row }">
            <Tooltip>
              <TooltipTrigger as-child>
                <Badge variant="outline" :class="healthTag(row).tone">{{ healthTag(row).label }}</Badge>
              </TooltipTrigger>
              <TooltipContent>
                {{ String(row.health_error || (row.health_elapsed_ms != null ? `${row.health_elapsed_ms} ms` : '尚未探测')) }}
              </TooltipContent>
            </Tooltip>
          </template>
          <template #rtt="{ row }">
            <span class="mono">
              {{ row.health_elapsed_ms == null ? '—' : `${Math.round(Number(row.health_elapsed_ms))} ms` }}
            </span>
          </template>
          <template #actions="{ row }">
            <Button variant="link" size="sm" @click="openProbe(row as unknown as AkshareCatalogCapability)">
              试跑
            </Button>
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

  <Dialog v-model:open="visible">
    <DialogContent
      class="probe-dialog w-[min(720px,96vw)] max-w-none gap-3 p-4 sm:max-w-none"
      @interact-outside="(event: Event) => event.preventDefault()"
    >
      <DialogHeader class="gap-1 text-left">
        <DialogTitle>{{ selected ? `试跑 ${selected.name}` : '接口试跑' }}</DialogTitle>
      </DialogHeader>
      <p v-if="selected" class="signature">{{ selected.signature }} · {{ selected.summary }}</p>
      <form class="params-form" @submit.prevent="submitProbe">
        <div v-for="parameter in selected?.parameters ?? []" :key="parameter.name" class="param-field">
          <Label :for="`probe-param-${parameter.name}`">
            {{ parameter.name }}
            <span v-if="parameter.required" class="text-stamp" aria-hidden="true">*</span>
          </Label>
          <Switch
            v-if="inputKind(parameter) === 'boolean'"
            :disabled="visitor"
            :model-value="boolParam(parameter.name)"
            :aria-label="parameter.name"
            :aria-invalid="Boolean(parameterErrors[parameter.name])"
            @update:model-value="(next: boolean) => { params[parameter.name] = next }"
          />
          <NumberField
            v-else-if="inputKind(parameter) === 'number'"
            :model-value="numberParam(parameter.name)"
            @update:model-value="(next: number | null | undefined) => { params[parameter.name] = next ?? null }"
          >
            <NumberFieldContent>
              <NumberFieldInput
                :id="`probe-param-${parameter.name}`"
                :aria-label="parameter.name"
                :aria-invalid="Boolean(parameterErrors[parameter.name])"
              />
              <NumberFieldIncrement />
              <NumberFieldDecrement />
            </NumberFieldContent>
          </NumberField>
          <Input
            v-else
            :id="`probe-param-${parameter.name}`"
            :model-value="textParam(parameter.name)"
            :aria-invalid="Boolean(parameterErrors[parameter.name])"
            :aria-label="parameter.name"
            @update:model-value="(next: string | number) => { params[parameter.name] = String(next) }"
          />
          <p class="parameter-meta">
            {{ parameter.kind }}<span v-if="parameter.annotation"> · {{ parameter.annotation }}</span>
            <span v-if="parameter.has_default"> · 默认：{{ String(parameter.default) }}</span>
            <span v-if="parameter.sample != null && parameter.sample !== parameter.default"> · 测试值：{{ String(parameter.sample) }}</span>
            <span v-else-if="parameter.sample != null"> · 示例：{{ String(parameter.sample) }}</span>
          </p>
          <p v-if="parameterErrors[parameter.name]" class="parameter-error" role="alert">
            {{ parameterErrors[parameter.name] }}
          </p>
        </div>
      </form>
      <Alert v-if="Object.keys(parameterErrors).length" variant="destructive">
        <AlertTitle class="line-clamp-none">{{ Object.values(parameterErrors).join(' ') }}</AlertTitle>
      </Alert>
      <Alert v-if="selectedProbeResult?.error" variant="destructive">
        <AlertTitle class="line-clamp-none">{{ selectedProbeResult.error }}</AlertTitle>
      </Alert>
      <div v-else-if="selectedProbeResult" class="probe-summary">
        RTT：{{ selectedProbeResult.elapsed_ms ?? '—' }} ms；行数：{{ selectedProbeResult.rows ?? '—' }}；列数：{{ sampleColumns.length }}
        <span v-if="selectedProbeResult.truncated">；样本已截断</span>
      </div>
      <BasicTable
        v-if="sampleRows.length"
        :columns="sampleTableColumns"
        :data-source="sampleRows"
        :pagination="false"
        max-height="240"
        empty-text="样本为空"
      />
      <DialogFooter class="gap-2">
        <Button access="read" variant="outline" @click="visible = false">关闭</Button>
        <Button :disabled="busy || !selected" @click="submitProbe">
          <LoaderCircle v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
          执行试跑
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
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
  gap: var(--gap-2);
}
.catalog-filters {
  gap: var(--gap-2);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  padding: var(--gap-2);
  background: var(--surface-sunken);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
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
/* 入参栅格：每个入参是一个 label + 控件 + 元信息的字段列，label 左缘与控件对齐 */
.params-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  gap: var(--gap-2) var(--gap-3);
  align-items: start;
}
.param-field { display: flex; min-width: 0; flex-direction: column; gap: var(--gap-1); }
.parameter-meta { margin: 2px 0 0; color: var(--mist); font-size: var(--fs-kicker); line-height: 1.35; }
.parameter-error { margin: 0; color: var(--stamp); font-size: var(--fs-kicker); font-weight: 500; }
.probe-summary { margin: var(--gap-2) 0; color: var(--mist); font-size: var(--fs-aux); font-variant-numeric: tabular-nums; }
.probe-dialog {
  max-height: 84dvh;
  overflow: auto;
  overscroll-behavior: contain;
}
</style>
