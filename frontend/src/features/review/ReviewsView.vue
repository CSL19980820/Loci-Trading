<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import Sparkline from '@/shared/components/charts/Sparkline.vue'
import TableFoot from '@/shared/components/ui/TableFoot.vue'
import { useClientPagination } from '@/shared/composables/useClientPagination'
import { entityLabel, pct, toneClass } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'

const store = usePalaceStore()
const route = useRoute()
const recordOpen = ref(false)

const { currentPage, pageSize, total, paginated: paginatedReviews } = useClientPagination(
  () => store.reviews,
  15,
)

const withReturn = computed(() => store.reviews.filter((item) => item.return_pct !== null).length)
const avgReturn = computed(() => {
  const values = store.reviews.map((item) => item.return_pct).filter((value): value is number => value !== null)
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
})
const returnSeries = computed(
  () => store.reviews.map((item) => item.return_pct).filter((value): value is number => value !== null).reverse(),
)

function onSaved(): void {
  void store.loadRoute(route, true)
}
</script>

<template>
  <PageHeader
    title="手记"
    :subtitle="`样本 ${withReturn} · 均 ${avgReturn === null ? '—' : `${avgReturn > 0 ? '+' : ''}${avgReturn.toFixed(1)}%`} · ${store.dashboard?.evolution.review_count ?? store.reviews.length}/${store.dashboard?.evolution.gate ?? 5}`"
  >
    <el-tag size="small" type="info">{{ store.reviews.length }}</el-tag>
    <RouterLink to="/reviews"><el-button>复盘中心</el-button></RouterLink>
    <el-button type="primary" @click="recordOpen = true">写复盘</el-button>
  </PageHeader>

  <Sheet v-if="returnSeries.length" title="收益示意" quiet margin>
    <div class="chart-box compact-chart">
      <Sparkline
        :values="returnSeries"
        :height="56"
        :color="(returnSeries[returnSeries.length - 1] ?? 0) >= 0 ? 'var(--up)' : 'var(--down)'"
        label="收益"
      />
    </div>
  </Sheet>

  <Sheet v-if="store.reviews.length">
    <el-collapse>
      <el-collapse-item v-for="item in paginatedReviews" :key="item.id" :name="item.id">
        <template #title>
          <div class="review-title">
            <span class="mono dim">{{ item.date }}</span>
            <el-tag size="small" type="info">{{ entityLabel(item.entity_type) }}</el-tag>
            <strong class="clip-title">{{ item.outcome }}</strong>
            <span class="mono" :class="toneClass(item.return_pct)">{{ pct(item.return_pct) }}</span>
          </div>
        </template>
        <div class="memory-metrics mono">
          <span class="dim">M{{ pct(item.max_favorable_pct) }}</span>
          <span class="dim">A{{ pct(item.max_adverse_pct) }}</span>
        </div>
        <p v-if="item.lesson" class="reason"><b>训</b> {{ item.lesson }}</p>
        <p v-if="item.next_rule" class="reason"><b>规</b> {{ item.next_rule }}</p>
        <div class="memory-foot mono dim">{{ item.id }} · {{ item.entity_id }}</div>
      </el-collapse-item>
    </el-collapse>
    <TableFoot v-model:page="currentPage" :total="total" :page-size="pageSize" />
  </Sheet>
  <EmptyState
    v-else
    description="还没有复盘"
    reason="还没写过复盘"
    eta="卖出或减仓后补记"
  >
    <el-button type="primary" @click="recordOpen = true">写复盘</el-button>
  </EmptyState>

  <RecordDialog v-model="recordOpen" kind="review" @saved="onSaved" />
</template>

<style scoped>
.review-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.55rem;
  padding-right: 0.5rem;
}

.clip-title {
  max-width: 16rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
