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
  <section class="dimension-rail research-surface" aria-label="研究维度目录">
    <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
    <header class="section-head">
      <h3>维度目录</h3>
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
          <el-button text class="dimension-name" :aria-pressed="row.key === props.selectedKey" :aria-label="`${row.name}，${qualityText(row.result?.quality)}`" @click.stop="select(row.key)">
            <el-icon :class="`quality-${row.result?.quality || 'missing'}`" aria-hidden="true">
              <component :is="statusIcon(row.result?.quality)" />
            </el-icon>
            <span :title="`${row.name} · ${row.key}`">{{ row.name }}</span>
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

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border-bottom: 1px solid var(--rule);
}

.section-head h3 {
  margin: var(--gap-1) 0 0;
  color: var(--ink);
  font-size: var(--fs-title);
  font-weight: 700;
  letter-spacing: 0;
}

.count-mark {
  min-inline-size: 2rem;
  padding: 0.2rem 0.45rem;
  border: 1px solid var(--rule);
  color: var(--mist);
  font: var(--fs-aux)/1.2 var(--mono);
  text-align: center;
}

.dimension-table {
  width: 100%;
}

.dimension-table :deep(.el-table__row) {
  cursor: pointer;
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
  font-size: var(--fs-aux);
  overflow-wrap: anywhere;
}

.quality-full {
  color: var(--ok);
}

.quality-partial {
  color: var(--seal-ink);
}

.quality-missing {
  color: var(--mist);
}

.quality-error {
  color: var(--warn);
}

@media (max-width: 820px) {
  .dimension-rail {
    max-height: 22rem;
    overflow: auto;
  }
}
</style>
<style scoped src="./ResearchSurfaces.css"></style>
