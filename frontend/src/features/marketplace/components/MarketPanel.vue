<script setup lang="ts">
import { useVisitorMode } from '@/shared/composables/useAccess'
import { computed, onMounted, ref, useId, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleAlert, RefreshCw, Upload, X } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { removeSkill } from '@/shared/api/quant'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
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

const visitor = useVisitorMode()
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
    if (visitor.value && (route.query.shelf === 'publish' || (!props.embedded && route.query.tab === 'publish'))) return 'browse'
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
  ...(!visitor.value ? [{ name: 'publish', label: '安装' }] : []),
])

const kindOptions: { value: MarketKind | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'strategy', label: KIND_LABEL.strategy },
  { value: 'skill', label: KIND_LABEL.skill },
  { value: 'source', label: KIND_LABEL.source },
]
const kindItems = kindOptions.map((opt) => ({ name: opt.value, label: opt.label }))

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
    toast.success(`已卸载 ${item.name}`)
    if (selectedId.value === item.id) select('')
    await load()
    emit('catalog-changed')
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '卸载失败'))
  }
}

/** shadcn 的 ToggleGroup 只吐字符串，回填时统一过 parseMarketKind 收敛口径 */
function onKindChange(next: unknown): void {
  kindFilter.value = parseMarketKind(next)
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
const panelId = `market-shelf-panel-${useId()}`
</script>

<template>
  <div class="market-panel flex min-h-0 min-w-0 flex-1 flex-col" :class="{ 'page-fill': !embedded }">
    <div class="market-subhead">
      <PageTabs :panel-id="panelId" class="market-shelf-tabs" v-model="shelfTab" :items="tabItems" :sticky="false" variant="pill" dense aria-label="市场货架分区" />
      <div class="market-actions">
        <Button access="read" variant="ghost" size="sm" :disabled="loading" @click="load">
          <RefreshCw :class="{ 'animate-spin motion-reduce:animate-none': loading }" aria-hidden="true" />
          刷新
        </Button>
        <Button v-if="shelfTab !== 'publish'" size="sm" @click="goPublish">
          <Upload aria-hidden="true" />
          安装技能
        </Button>
      </div>
    </div>

    <Alert v-if="error" variant="destructive" class="market-alert">
      <CircleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
        <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="error = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <div :id="panelId" class="market-body" role="tabpanel" tabindex="0" :aria-labelledby="`${panelId}-tab-${shelfTab}`">
      <template v-if="shelfTab !== 'publish'">
        <div class="market-toolbar">
          <PageTabs
            :model-value="kindFilter"
            :items="kindItems"
            variant="pill"
            dense
            :sticky="false"
            aria-label="货品分类"
            @update:model-value="onKindChange"
          />
          <Badge v-if="!loading" variant="secondary">{{ shelfRows.length }} 项</Badge>
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
              <EmptyState :description="error ? '货架加载失败' : '暂无此类货品'" :reason="error ? '稍后重试或检查网络' : '安装技能包后会出现在这里'">
                <Button access="read" v-if="error" variant="outline" size="sm" @click="load">
                  <RefreshCw aria-hidden="true" />
                  重试
                </Button>
                <Button v-else size="sm" @click="goPublish">
                  <Upload aria-hidden="true" />
                  安装技能
                </Button>
              </EmptyState>
            </template>
          </MarketShelfTable>
        </section>
      </template>

      <MarketPublishPanel
        v-else
        @installed="onInstalled"
        @notice="(msg) => toast.success(msg)"
        @error="(msg) => toast.error(msg)"
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
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
}
.market-shelf-tabs {
  min-width: 0;
  margin: 0;
  padding: 0;
  background: transparent;
}
.market-actions,
.market-toolbar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}
.market-toolbar {
  justify-content: space-between;
}
.market-alert {
  flex-shrink: 0;
  margin: var(--gap-3) 0 0;
}

.market-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--gap-3);
  min-width: 0;
  min-height: 0;
  padding-top: var(--gap-3);
  overflow: hidden;
}

/* 高度内容驱动：货架空时不留 12rem 死白，长列表由表体自滚 */
.market-shelf-wrap {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}
@media (max-width: 640px) {
  .market-shelf-tabs {
    flex-basis: 100%;
  }
  .market-actions {
    margin-left: auto;
  }
}
</style>
