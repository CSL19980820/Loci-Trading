<script setup lang="ts">
import {
  CircleCheck,
  CircleClose,
  WarningFilled,
} from '@element-plus/icons-vue'

import type { ResearchQuality } from '@/shared/types/quant'

import type { ResearchDimensionRow } from '../researchTypes'

const props = defineProps<{
  rows: ResearchDimensionRow[]
  selectedKey: string
}>()

const emit = defineEmits<{
  select: [key: string]
}>()

function qualityText(value: ResearchQuality | undefined): string {
  if (value === 'full') return '完整'
  if (value === 'partial') return '部分完整'
  if (value === 'error') return '计算错误'
  return '缺失'
}

function qualityType(value: ResearchQuality | undefined): 'success' | 'warning' | 'info' | 'danger' {
  if (value === 'full') return 'success'
  if (value === 'partial') return 'warning'
  if (value === 'error') return 'danger'
  return 'info'
}

function statusIcon(value: ResearchQuality | undefined) {
  if (value === 'full') return CircleCheck
  if (value === 'error') return CircleClose
  return WarningFilled
}

function select(key: string): void {
  emit('select', key)
}
</script>

<template>
  <section class="dimension-rail" aria-label="研究维度目录">
    <header class="section-head">
      <div>
        <span class="research-kicker">DIMENSION MAP</span>
        <h3>维度目录</h3>
      </div>
      <span class="count-mark">{{ props.rows.length }}</span>
    </header>
    <el-table
      :data="props.rows"
      :current-row-key="props.selectedKey"
      size="small"
      row-key="key"
      highlight-current-row
      class="dimension-table"
      :show-header="false"
      @row-click="(row: ResearchDimensionRow) => select(row.key)"
    >
      <el-table-column min-width="180">
        <template #default="{ row }">
          <el-button text class="dimension-name" @click.stop="select(row.key)">
            <el-icon :class="`quality-${row.result?.quality || 'missing'}`" aria-hidden="true">
              <component :is="statusIcon(row.result?.quality)" />
            </el-icon>
            <span>{{ row.name }}</span>
            <code>{{ row.key }}</code>
          </el-button>
        </template>
      </el-table-column>
      <el-table-column width="82" align="right">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="qualityType(row.result?.quality)">
            {{ qualityText(row.result?.quality) }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<style scoped>
.dimension-rail {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.research-kicker {
  display: block;
  color: var(--mist);
  font: 0.68rem/1.2 var(--mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.82rem 0.9rem;
  border-bottom: 1px solid var(--rule);
}

.section-head h3 {
  margin: 0.22rem 0 0;
  color: var(--ink);
  font-size: 0.98rem;
  font-weight: 700;
  letter-spacing: 0;
}

.count-mark {
  min-inline-size: 2rem;
  padding: 0.2rem 0.45rem;
  border: 1px solid var(--rule);
  color: var(--mist);
  font: 0.75rem/1.2 var(--mono);
  text-align: center;
}

.dimension-table {
  width: 100%;
}

.dimension-table :deep(.el-table__row) {
  cursor: pointer;
}

.dimension-table :deep(.el-table__cell) {
  padding: 0.45rem 0.55rem;
}

.dimension-name {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.4rem;
  max-width: 100%;
  padding-inline: 0;
  color: var(--ink);
  white-space: normal;
  text-align: start;
}

.dimension-name code {
  color: var(--mist);
  font-family: var(--mono);
  font-size: 0.74rem;
  overflow-wrap: anywhere;
}

.quality-full {
  color: var(--lake);
}

.quality-partial {
  color: var(--seal);
}

.quality-missing {
  color: var(--mist);
}

.quality-error {
  color: var(--loss);
}

@media (max-width: 820px) {
  .dimension-rail {
    max-height: 22rem;
    overflow: auto;
  }
}
</style>
