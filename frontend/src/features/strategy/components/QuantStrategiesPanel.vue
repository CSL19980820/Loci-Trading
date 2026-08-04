<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Plus, RefreshRight, Search } from '@element-plus/icons-vue'

import PageContainer from '@/shared/components/layout/PageContainer.vue'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import { formValuesEqual } from '@/shared/components/ui/basicFormEqual'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import RowActions from '@/shared/components/ui/RowActions.vue'
import type { StrategyInfo } from '@/shared/types/quant'

import StrategyDetailDialog from './StrategyDetailDialog.vue'

function sourceKindLabel(kind: string | null | undefined): string {
  if (kind === 'builtin') return '内置'
  if (kind === 'formula') return '公式'
  return kind ? String(kind) : '—'
}

function revisionLabel(revision: string | null | undefined, sourceKind?: string | null): string {
  const raw = String(revision || '').trim()
  if (!raw) return '—'
  if (sourceKind === 'builtin' || raw.startsWith('builtin:')) return '内置'
  // 公式战法修订多为内容哈希
  if (/^[0-9a-f]{8,}$/i.test(raw)) return `公式 · ${raw.slice(0, 8)}`
  if (raw.startsWith('formula:')) return `公式 · ${raw.slice(8, 16) || '—'}`
  return raw.startsWith('公式') ? raw : `公式 · ${raw.slice(0, 8)}`
}

const props = defineProps<{
  strategies: StrategyInfo[]
  loading?: boolean
}>()

const emit = defineEmits<{
  openScreen: [slug: string]
}>()

const router = useRouter()
const route = useRoute()
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const nameQuery = ref('')
const detailOpen = ref(false)
const detail = ref<StrategyInfo | null>(null)

watch(
  () => [props.strategies, route.query.strategy] as const,
  ([list, raw]) => {
    const slug = String(raw || '').trim()
    if (!slug || !list.length) return
    const hit = list.find((s) => s.slug === slug)
    if (!hit) return
    openDetail(hit)
    const nextQuery = { ...route.query }
    delete nextQuery.strategy
    void router.replace({ query: nextQuery })
  },
  { immediate: true },
)

const filters = reactive({
  name: '',
})

const filterModel = computed({
  get: () => filters as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    const next = String(value.name ?? '')
    if (!formValuesEqual(filters.name, next)) filters.name = next
  },
})

const filterSchemas: BasicFormSchema[] = [
  {
    field: 'name',
    label: '名称',
    component: 'input',
    colSpan: 8,
    componentProps: {
      clearable: true,
      placeholder: '模糊查询战法名',
      maxlength: 64,
    },
  },
]

const filteredRows = computed(() => {
  const q = nameQuery.value.trim().toLowerCase()
  const list = !q
    ? props.strategies
    : props.strategies.filter(
        (row) =>
          row.name.toLowerCase().includes(q)
          || row.slug.toLowerCase().includes(q)
          || String(row.description || '').toLowerCase().includes(q),
      )
  return list as unknown as Record<string, unknown>[]
})

const columns = ref<BasicTableColumn[]>([
  {
    prop: 'name',
    label: '名称',
    minWidth: 180,
    slotName: 'name',
  },
  {
    prop: 'source_kind',
    label: '来源',
    width: 92,
    slotName: 'source',
  },
  {
    prop: 'entry_timing',
    label: '入场',
    width: 110,
    formatter: (row) => {
      const value = row.entry_timing as StrategyInfo['entry_timing']
      if (value === 'open') return '当日开盘'
      if (value === 'close') return '当日收盘'
      if (value === 'next_dip') return '次日低吸'
      return '次日开盘'
    },
  },
  {
    prop: 'min_bars',
    label: '最少K线',
    align: 'right',
    width: 100,
  },
  {
    prop: 'strategy_revision',
    label: '修订',
    width: 118,
    slotName: 'revision',
  },
  {
    prop: 'actions',
    label: '操作',
    align: 'right',
    width: 168,
    fixed: 'right',
    slotName: 'actions',
  },
])

function handleSubmit(): void {
  nameQuery.value = filters.name
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  filters.name = ''
  nameQuery.value = ''
}

function openDetail(row: StrategyInfo): void {
  detail.value = row
  detailOpen.value = true
}

function openWorkbench(query: Record<string, string | undefined>): void {
  void router.push({
    path: '/strategy-converter',
    query,
  })
}

function openEditableStrategy(slug: string): void {
  openWorkbench({ slug })
}

	function openCreate(source: 'blank' | 'description' | 'tdx'): void {
	  openWorkbench({ source })
	}

function onRowClick(row: Record<string, unknown>): void {
  openDetail(row as unknown as StrategyInfo)
}
</script>

<template>
  <div class="strategies-panel">
    <PageContainer>
      <template #search>
        <div class="strategies-search-form">
          <BasicForm
            ref="basicFormRef"
            v-model="filterModel"
            :schemas="filterSchemas"
            :col-props="{ span: 8 }"
            :input-debounce-ms="0"
            label-width="48px"
          />
        </div>
        <div class="strategies-search-actions">
          <el-button type="primary" :icon="Search" @click="handleSubmit">查询</el-button>
          <el-button :icon="RefreshRight" @click="handleReset">重置</el-button>
          <el-dropdown trigger="click" @command="openCreate">
            <el-button type="success" :icon="Plus">
              新建
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="blank">空白新建</el-dropdown-item>
                <el-dropdown-item command="description">AI 草稿</el-dropdown-item>
                <el-dropdown-item command="tdx">TDX 草稿</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </template>
      <template #main>
        <BasicTable
          v-if="filteredRows.length || loading"
          v-model:columns="columns"
          :data-source="filteredRows"
          :pagination="false"
          :loading="loading"
          stripe
          row-key="slug"
          empty-text="无匹配战法"
          @row-click="onRowClick"
        >
          <template #name="{ row }">
            <div class="name-cell">
              <div class="name-line">
                <strong>{{ row.name }}</strong>
                <el-tag v-if="row.editable" size="small" type="success" effect="plain">可编辑</el-tag>
                <el-tag v-else size="small" effect="plain">只读</el-tag>
              </div>
            </div>
          </template>
          <template #source="{ row }">
            <el-tag size="small" :type="row.source_kind === 'builtin' ? 'info' : 'danger'" effect="plain">
              {{ sourceKindLabel(String(row.source_kind)) }}
            </el-tag>
          </template>
          <template #revision="{ row }">
            <span class="dim">
              {{ revisionLabel(String(row.strategy_revision || ''), String(row.source_kind || '')) }}
            </span>
          </template>
          <template #actions="{ row }">
            <RowActions
              :max-visible="3"
              :actions="[
                {
                  key: 'open',
                  label: '选股',
                  onClick: () => emit('openScreen', String(row.slug)),
                },
                {
                  key: 'config',
                  label: '配置',
                  onClick: () => openDetail(row as unknown as StrategyInfo),
                },
                ...(row.editable
                  ? [
                      {
                        key: 'edit',
                        label: '编辑公式',
                        onClick: () => openEditableStrategy(String(row.slug)),
                      },
                    ]
                  : []),
              ]"
            />
          </template>
        </BasicTable>
        <EmptyState
          v-else
          description="还没有量化选股战法"
          reason="自定义战法在量化技能工坊维护，builtin 战法由产品内置。"
          eta="可直接新建、生成草稿，或去市场安装。"
        >
          <el-dropdown trigger="click" @command="openCreate">
            <el-button type="primary" :icon="Plus">
              新建
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="blank">空白新建</el-dropdown-item>
                <el-dropdown-item command="description">AI 草稿</el-dropdown-item>
                <el-dropdown-item command="tdx">TDX 草稿</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </EmptyState>
      </template>
    </PageContainer>

    <StrategyDetailDialog v-model="detailOpen" :strategy="detail" />
  </div>
</template>

<style scoped>
.strategies-panel {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.strategies-search-form {
  flex: 1;
  min-width: 0;
}

.strategies-search-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
  padding-bottom: 0.65rem;
}

.name-cell {
  min-width: 0;
}

.name-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.dim {
  color: var(--mist);
  font-size: 0.76rem;
}
</style>
