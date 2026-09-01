<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { removeSkill } from '@/shared/api/quant'
import HeaderActions from '@/shared/components/layout/HeaderActions.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'

import MarketDetailDialog from './MarketDetailDialog.vue'
import MarketPublishPanel from './MarketPublishPanel.vue'
import MarketShelfTable from './MarketShelfTable.vue'
import {
  KIND_LABEL,
  parseMarketKind,
  parseMarketTab,
  useMarketCatalog,
  type MarketKind,
  type MarketPackage,
  type MarketTab,
} from '../composables/useMarketCatalog'

const props = withDefaults(
  defineProps<{
    /** 嵌在工坊内时收起大标题，货架子区走 ?shelf= */
    embedded?: boolean
  }>(),
  { embedded: false },
)

const emit = defineEmits<{
  'catalog-changed': []
}>()

const route = useRoute()
const router = useRouter()

const {
  filtered,
  installed,
  selected,
  selectedId,
  kindFilter,
  loading,
  error,
  counts,
  select,
  load,
} = useMarketCatalog()

/** 货架子区：独立路由曾用 ?tab=；工坊内用 ?shelf= 避免与工坊 tab 冲突 */
const shelfTab = computed({
  get: () => {
    if (props.embedded) return parseMarketTab(route.query.shelf)
    return parseMarketTab(route.query.shelf ?? route.query.tab)
  },
  set: (tab: MarketTab) => {
    const nextShelf = tab === 'browse' ? undefined : tab
    if (props.embedded) {
      void router.replace({
        query: {
          ...route.query,
          tab: 'market',
          shelf: nextShelf,
        },
      })
      return
    }
    void router.replace({
      query: {
        ...route.query,
        tab: nextShelf,
        shelf: undefined,
      },
    })
  },
})

const shelfRows = computed(() => (shelfTab.value === 'installed' ? installed.value : filtered.value))

const detailOpen = ref(false)

const tabItems = computed(() => [
  { name: 'browse', label: '浏览', badge: counts.value.all || undefined },
  { name: 'installed', label: '已装', badge: installed.value.length || undefined },
  { name: 'publish', label: '发布' },
])

const kindOptions: { value: MarketKind | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'strategy', label: KIND_LABEL.strategy },
  { value: 'skill', label: KIND_LABEL.skill },
  { value: 'source', label: KIND_LABEL.source },
]

watch(
  () => route.query.kind,
  (raw) => {
    kindFilter.value = parseMarketKind(raw)
  },
  { immediate: true },
)

watch(kindFilter, (kind) => {
  const current = parseMarketKind(route.query.kind)
  if (kind === current) return
  void router.replace({
    query: {
      ...route.query,
      kind: kind === 'all' ? undefined : kind,
    },
  })
})

function goPublish(): void {
  shelfTab.value = 'publish'
}

function openPackage(item: MarketPackage): void {
  if (item.kind === 'source') {
    void router.push({ path: '/quant', query: { tab: 'sources' } })
    return
  }
  if (item.kind === 'strategy' && item.editable) {
    void router.push({ path: '/strategy-converter', query: { slug: item.slug } })
    return
  }
  const selectId = item.kind === 'strategy' ? `engine:${item.slug}` : `skill:${item.slug}`
  void router.push({ path: '/screen-history', query: { select: selectId } })
}

async function removePackage(item: MarketPackage): Promise<void> {
  if (!item.removable || item.kind !== 'skill') return
  if (!(await confirmDangerous(`确定卸载技能包「${item.name}」？`, '确认卸载', '卸载'))) return
  try {
    await removeSkill(item.slug)
    ElMessage.success(`已卸载 ${item.name}`)
    if (selectedId.value === item.id) select('')
    await load()
    emit('catalog-changed')
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '卸载失败'))
  }
}

/** 行点击=看详情；操作按钮由 RowActions 拦住冒泡，不会开弹层 */
function onRowSelect(id: string): void {
  select(id)
  if (selected.value) detailOpen.value = true
}

function openFromDetail(item: MarketPackage): void {
  detailOpen.value = false
  openPackage(item)
}

async function removeFromDetail(item: MarketPackage): Promise<void> {
  detailOpen.value = false
  await removePackage(item)
}

function onInstalled(): void {
  shelfTab.value = 'installed'
  kindFilter.value = 'skill'
  void load().then(() => emit('catalog-changed'))
}

onMounted(() => {
  void load()
})

defineExpose({ load })
</script>

<template>
  <div class="market-panel" :class="{ 'market-panel--embedded': embedded }">
    <div class="market-subhead">
      <PageTabs v-model="shelfTab" :items="tabItems" :sticky="false" dense aria-label="市场货架分区" />
      <HeaderActions
        :actions="[
          { key: 'reload', label: '刷新', disabled: loading, onClick: () => void load() },
          { key: 'publish', label: '安装 zip', kind: 'primary', onClick: goPublish },
        ]"
      />
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      class="market-alert"
      @close="error = ''"
    />

    <div class="market-body">
      <template v-if="shelfTab !== 'publish'">
        <div class="market-toolbar">
          <el-radio-group v-model="kindFilter" size="small">
            <el-radio-button v-for="opt in kindOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
        </div>

        <PageBusy v-if="loading && !shelfRows.length" label="加载货架…" />
        <section v-else-if="shelfRows.length" class="market-shelf-wrap" aria-label="货架">
          <MarketShelfTable
            :rows="shelfRows"
            :selected-id="selectedId"
            :loading="loading"
            :show-remove="shelfTab === 'installed'"
            @select="onRowSelect"
            @open="openPackage"
            @remove="removePackage"
          />
        </section>
        <EmptyState
          v-else
          description="货架还没有这类货品"
  reason="去「发布」安装 Skill zip"
        >
          <el-button type="primary" @click="goPublish">去发布 / 安装</el-button>
        </EmptyState>
      </template>

      <MarketPublishPanel
        v-else
        @installed="onInstalled"
        @notice="(msg) => ElMessage.success(msg)"
        @error="(msg) => ElMessage.error(msg)"
      />
    </div>

    <MarketDetailDialog
      v-model="detailOpen"
      :item="selected"
      :show-remove="shelfTab === 'installed'"
      @open="openFromDetail"
      @remove="removeFromDetail"
    />
  </div>
</template>

<style scoped>
.market-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* flex:1 已吃满父级高度；再写 height:100% 只会互相打架（体检 §4.4） */
  flex: 1 1 auto;
}

.market-panel--embedded {
  background: transparent;
}

.market-subhead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  flex-shrink: 0;
  padding-right: 0.35rem;
}

.market-subhead :deep(.page-tabs) {
  flex: 1;
  min-width: 0;
  margin-bottom: 0.45rem;
  padding-left: 0;
  padding-right: 0;
  background: transparent;
}

.market-alert {
  margin: 0 0 0.55rem;
  flex-shrink: 0;
}

.market-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.15rem 0 0.5rem;
}

.market-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  flex-shrink: 0;
}

/* 高度内容驱动：货架空时不留 12rem 死白，长列表由表体自滚 */
.market-shelf-wrap {
  flex: 1 1 auto;
  min-height: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

</style>
