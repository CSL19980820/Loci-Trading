<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { artifactShellTitle, parseTablePayload } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

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
</script>

<template>
  <section class="assistant-data-table" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-data-table__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
      <el-tag size="small" type="info">{{ payload.rows.length }} 行</el-tag>
    </div>
    <template v-if="payload.columns.length && payload.rows.length">
      <el-table
        :data="pagedRows"
        size="small"
        stripe
        border
        max-height="280"
        empty-text="无数据"
      >
        <el-table-column
          v-for="col in payload.columns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :width="col.width"
          min-width="72"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ cellText(row[col.prop]) }}</template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="payload.paginate"
        v-model:current-page="page"
        class="assistant-data-table__pager"
        layout="prev, pager, next"
        small
        :page-size="payload.pageSize"
        :total="payload.rows.length"
      />
    </template>
    <el-empty v-else :image-size="48" description="工具未返回表格数据" />
  </section>
</template>

<style scoped>
.assistant-data-table {
  margin-top: .15rem; padding: .55rem; border: 1px solid var(--rule);
  border-radius: var(--radius); background: var(--panel-2); width: 100%; min-width: 0;
}
.assistant-data-table__heading {
  display: flex; align-items: center; justify-content: space-between; gap: .4rem; margin-bottom: .4rem;
}
.assistant-data-table h3 { margin: 0; font-size: var(--ai-fs-body); }
.assistant-data-table__pager { margin-top: .45rem; justify-content: flex-end; }
</style>
