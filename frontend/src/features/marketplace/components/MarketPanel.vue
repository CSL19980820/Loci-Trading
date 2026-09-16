<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshRight, Upload } from '@element-plus/icons-vue'

import { removeSkill } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
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
  { name: 'publish', label: '安装' },
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
  <div class="market-panel flex min-h-0 min-w-0 flex-1 flex-col" :class="{ 'page-fill': !embedded }">
    <div class="market-subhead">
      <PageTabs class="market-shelf-tabs" v-model="shelfTab" :items="tabItems" :sticky="false" dense aria-label="市场货架分区" />
      <div class="market-actions">
        <el-button :icon="RefreshRight" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="shelfTab !== 'publish'" type="primary" :icon="Upload" @click="goPublish">安装技能</el-button>
      </div>
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
          <el-radio-group v-model="kindFilter" size="small" aria-label="货品分类">
            <el-radio-button v-for="opt in kindOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
          <UiBadge v-if="!loading" variant="secondary">{{ shelfRows.length }} 项</UiBadge>
        </div>

        <section class="market-shelf-wrap" aria-label="货架">
          <MarketShelfTable
            :rows="shelfRows"
            :selected-id="selectedId"
            :loading="loading"
            :show-remove="shelfTab === 'installed'"
            @select="onRowSelect"
            @open="openPackage"
            @remove="removePackage"
          >
            <template #empty>
              <EmptyState :description="error ? '货架加载失败' : '暂无此类货品'">
                <el-button v-if="error" :icon="RefreshRight" @click="load">重试</el-button>
                <el-button v-else type="primary" :icon="Upload" @click="goPublish">安装技能</el-button>
              </EmptyState>
            </template>
          </MarketShelfTable>
        </section>
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
.market-subhead {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap-2);
  flex-shrink: 0;
}
.market-shelf-tabs {
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 0;
  background: transparent;
}
.market-actions,
.market-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap-2);
  flex-shrink: 0;
}
.market-actions :deep(.el-button + .el-button) { margin-left: 0; }
.market-toolbar { justify-content: space-between; }
.market-alert {
  margin: var(--gap-2) 0 0;
  flex-shrink: 0;
}

.market-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  gap: var(--gap-2);
  padding-top: var(--gap-2);
  overflow: hidden;
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
@media (max-width: 640px) {
  .market-shelf-tabs { flex-basis: 100%; }
  .market-actions { margin-left: auto; }
}

</style>
