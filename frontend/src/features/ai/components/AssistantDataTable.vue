<script setup lang="ts">
import { Card, CardHeader, CardContent, CardTitle } from '@/shared/components/ui/card'
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'

import { artifactShellTitle, parseTablePayload } from '../assistantArtifacts'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Badge } from '@/shared/components/ui/badge'
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/shared/components/ui/pagination'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const page = ref(1)
const payload = computed(() => parseTablePayload(props.artifact.data ?? {}))

watch(() => props.artifact.id, () => { page.value = 1 })

const pagedRows = computed(() => {
  if (!payload.value.paginate) return payload.value.rows
  const size = payload.value.pageSize
  const start = (page.value - 1) * size
  return payload.value.rows.slice(start, start + size)
})

function cellText(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') {
    try { return JSON.stringify(value) } catch { return '—' }
  }
  return String(value)
}

/** 工具返回的列是动态的，所以 `columns` 也是算出来的；单元格统一走 formatter。 */
const columns = computed<BasicTableColumn[]>(() =>
  payload.value.columns.map((col) => ({
    prop: col.prop,
    label: col.label,
    width: col.width,
    minWidth: 72,
    showOverflowTooltip: true,
    formatter: (row: Record<string, unknown>) => cellText(row[col.prop]),
  })),
)
</script>

<template>
  <Card class="assistant-data-table assistant-card" :aria-label="artifactShellTitle(artifact)">
    <CardHeader class="assistant-card__heading">
      <CardTitle>{{ artifactShellTitle(artifact) }}</CardTitle>
      <Badge variant="outline">{{ payload.rows.length }} 行</Badge>
    </CardHeader>
    <CardContent class="assistant-card__content">
    <template v-if="columns.length">
      <BasicTable
        class="assistant-data-table__table"
        :columns="columns"
        :data-source="pagedRows"
        :pagination="false"
        stripe
        border
        max-height="280"
        empty-text="无数据"
      />
      <Pagination
        v-if="payload.paginate"
        v-model:page="page"
        class="assistant-data-table__pager"
        :total="payload.rows.length"
        :items-per-page="payload.pageSize"
        :sibling-count="1"
        show-edges
      >
        <PaginationContent v-slot="{ items }">
          <PaginationPrevious aria-label="上一页">
            <ChevronLeft />
          </PaginationPrevious>
          <template v-for="(item, index) in items" :key="index">
            <PaginationItem
              v-if="item.type === 'page'"
              :value="item.value"
              :is-active="item.value === page"
            >
              {{ item.value }}
            </PaginationItem>
            <PaginationEllipsis v-else :index="index" />
          </template>
          <PaginationNext aria-label="下一页">
            <ChevronRight />
          </PaginationNext>
        </PaginationContent>
      </Pagination>
    </template>
    <EmptyState v-else description="工具未返回表格数据" reason="缩小范围重问" />
    </CardContent>
  </Card>
</template>

<style scoped>
/* 消息里的表格：横向可滚，不把正文列撑爆 */
.assistant-data-table__table {
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: thin;
}
.assistant-data-table__table :deep(td),
.assistant-data-table__table :deep(th) {
  white-space: nowrap;
}
.assistant-data-table__pager {
  width: auto;
  justify-content: flex-end;
  margin-top: var(--gap-2);
}
.assistant-data-table__pager :deep(button) {
  height: var(--row-h-sm);
  min-width: var(--row-h-sm);
}
</style>
