<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'
import QueryFilterBar from '@/shared/components/ui/QueryFilterBar.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import type { Candidate } from '@/shared/types/palace'

defineProps<{
  candStrategy: string
  candidates: Candidate[]
  busy: boolean
}>()

const emit = defineEmits<{
  'update:candStrategy': [string]
  query: []
}>()
</script>

<template>
  <QueryFilterBar
    :model-value="candStrategy"
    placeholder="战法 / 规则版本"
    :busy="busy"
    @update:model-value="emit('update:candStrategy', $event)"
    @query="emit('query')"
  >
    <RouterLink to="/pool"><el-button>打开候选池</el-button></RouterLink>
  </QueryFilterBar>
  <Sheet title="候选记录" :chip="candidates.length">
    <el-table :data="candidates" size="small" empty-text="无候选">
      <el-table-column label="日期" prop="date" width="110" />
      <el-table-column label="战法" prop="rule_version" width="110" />
      <el-table-column label="标的" min-width="140">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" />
        </template>
      </el-table-column>
      <el-table-column label="裁决" prop="decision" width="90" />
      <el-table-column label="评分" align="right" width="80">
        <template #default="{ row }">{{ row.score ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="理由" prop="reason" min-width="200" show-overflow-tooltip />
    </el-table>
  </Sheet>
</template>
