<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { InfoFilled } from '@element-plus/icons-vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import Sparkline from '@/shared/components/charts/Sparkline.vue'
import { useClientPagination } from '@/shared/composables/useClientPagination'
import { entityLabel, pct, toneClass } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'

const store = usePalaceStore()
const route = useRoute()
const recordOpen = ref(false)

/** 口径不占正文行：只作表格工具行上的一枚 ⓘ */
const PAGE_NOTE = '手工补记的样本与教训'

const { currentPage, pageSize, total, paginated: paginatedReviews } = useClientPagination(
  () => store.reviews,
  15,
)

const returnSeries = computed(
  () => store.reviews.map((item) => item.return_pct).filter((value): value is number => value !== null).reverse(),
)

const columns = ref<BasicTableColumn[]>([
  { prop: 'date', label: '日期', width: 110 },
  { prop: 'entity_type', label: '类型', width: 88, slotName: 'entity' },
  { prop: 'outcome', label: '结果', minWidth: 160, showOverflowTooltip: true },
  { prop: 'return_pct', label: '收益', width: 88, slotName: 'ret' },
  { prop: 'mae_mfe', label: '最高浮盈 / 最深浮亏', width: 170, slotName: 'maeMfe' },
  {
    prop: 'lesson',
    label: '训 / 规',
    minWidth: 200,
    align: 'left',
    headerAlign: 'left',
    slotName: 'lesson',
    showOverflowTooltip: true,
  },
])

const tableRows = computed(() => paginatedReviews.value as unknown as Record<string, unknown>[])

/** 类型 tag 三色克制区分：候选=主题色、预案=暖色、成交=青绿；全部 plain 描边 */
function entityTagType(type: string): 'primary' | 'warning' | 'success' | 'info' {
  if (type === 'candidate') return 'primary'
  if (type === 'plan') return 'warning'
  if (type === 'trade') return 'success'
  return 'info'
}

function onSaved(): void {
  void store.loadRoute(route, true)
}
</script>

<template>
  <div class="page-fill">
    <PageContainer>
      <template v-if="returnSeries.length" #topExpand>
        <div class="spark-wrap">
          <Sparkline
            :values="returnSeries"
            :height="48"
            :color="(returnSeries[returnSeries.length - 1] ?? 0) >= 0 ? 'var(--up)' : 'var(--down)'"
            label="收益"
          />
        </div>
      </template>
      <template #main>
        <BasicTable
          v-if="store.reviews.length"
          v-model:columns="columns"
          :data-source="tableRows"
          :pagination="{
            currentPage,
            pageSize,
            total,
            hideOnSinglePage: true,
            layout: 'total, prev, pager, next',
          }"
          :toolbar-config="{ custom: true }"
          stripe
          row-key="id"
          @current-change="(page) => { currentPage = page }"
        >
          <!-- 主动作与口径并进表格自带的工具行：页面不再单开一条页头（任务 3） -->
          <template #toolbarButtons>
            <el-button type="primary" size="small" @click="recordOpen = true">补记一笔</el-button>
            <el-tooltip :content="PAGE_NOTE" placement="bottom-start" :show-after="200">
              <el-icon class="toolbar-note" tabindex="0" :aria-label="PAGE_NOTE"><InfoFilled /></el-icon>
            </el-tooltip>
          </template>
          <template #entity="{ row }">
            <el-tag size="small" effect="plain" :type="entityTagType(String(row.entity_type))">
              {{ entityLabel(String(row.entity_type)) }}
            </el-tag>
          </template>
          <template #ret="{ row }">
            <span class="mono" :class="toneClass(row.return_pct as number | null)">
              {{ pct(row.return_pct as number | null) }}
            </span>
          </template>
          <template #maeMfe="{ row }">
            <span class="mono dim">
              盈 {{ pct(row.max_favorable_pct as number | null) }}
              · 亏 {{ pct(row.max_adverse_pct as number | null) }}
            </span>
          </template>
          <template #lesson="{ row }">
            <span v-if="row.lesson || row.next_rule" class="lesson-cell">
              <template v-if="row.lesson">训 {{ row.lesson }}</template>
              <template v-if="row.lesson && row.next_rule"> · </template>
              <template v-if="row.next_rule">规 {{ row.next_rule }}</template>
            </span>
            <span v-else class="dim">—</span>
          </template>
        </BasicTable>
        <PageBusy v-else-if="store.loading" label="加载复盘…" />
        <EmptyState
          v-else
          description="还没有复盘记录"
          reason="卖出或减仓后可补记一笔"
        >
          <el-button type="primary" @click="recordOpen = true">补记一笔</el-button>
        </EmptyState>
      </template>
    </PageContainer>

    <RecordDialog v-model="recordOpen" kind="review" @saved="onSaved" />
  </div>
</template>

<style scoped>
.spark-wrap {
  padding: var(--gap-1) var(--gap-3);
  border-bottom: 1px solid var(--rule);
}

.lesson-cell {
  font-size: var(--fs-aux);
  color: var(--muted);
}

/* 口径提示：一枚 ⓘ，不占文本宽度 */
.toolbar-note {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
  cursor: help;
}

.toolbar-note:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: 2px;
  border-radius: var(--radius);
}
</style>
