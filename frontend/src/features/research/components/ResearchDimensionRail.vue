<script setup lang="ts">
import { CircleCheck, CircleX, TriangleAlert } from '@lucide/vue'

import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
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

/**
 * 质量档 → 语义色。shadcn Badge 只有 default/secondary/destructive/outline，
 * 状态色由令牌类补上（与配色规范 D1 的状态色一致，不借涨跌色）。
 */
const QUALITY_TONE: Record<'success' | 'warning' | 'info' | 'danger', string> = {
  success: 'border-transparent bg-ok-soft text-ok',
  warning: 'border-transparent bg-warn-soft text-warn-ink',
  info: 'border-line bg-sunken text-mist',
  danger: 'text-stamp border-[color-mix(in_oklab,var(--stamp)_38%,var(--rule))] bg-surface',
}

function qualityType(value: ResearchQuality | undefined): 'success' | 'warning' | 'info' | 'danger' {
  if (value === 'full') return 'success'
  if (value === 'partial') return 'warning'
  if (value === 'error') return 'danger'
  return 'info'
}

function statusIcon(value: ResearchQuality | undefined) {
  if (value === 'full') return CircleCheck
  if (value === 'error') return CircleX
  return TriangleAlert
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

    <ul v-if="props.rows.length" class="dimension-list" role="list">
      <li
        v-for="row in props.rows"
        :key="row.key"
        class="dimension-row"
        :class="{ 'is-current': row.key === props.selectedKey }"
        @click="select(row.key)"
      >
        <Button access="read"
          variant="ghost"
          class="dimension-name"
          :aria-pressed="row.key === props.selectedKey"
          :aria-label="`${row.name}，${qualityText(row.result?.quality)}`"
          @click.stop="select(row.key)"
        >
          <component
            :is="statusIcon(row.result?.quality)"
            :class="`quality-${row.result?.quality || 'missing'}`"
            aria-hidden="true"
          />
          <span :title="`${row.name} · ${row.key}`">{{ row.name }}</span>
        </Button>
        <Badge variant="outline" :class="QUALITY_TONE[qualityType(row.result?.quality)]">
          {{ qualityText(row.result?.quality) }}
        </Badge>
      </li>
    </ul>
    <EmptyState v-else description="维度目录为空" reason="重新读取研究目录" />
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

.dimension-list {
  display: flex;
  min-width: 0;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.dimension-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  min-width: 0;
  padding: 0 var(--gap-2) 0 0;
  border-bottom: 1px solid var(--rule);
  cursor: pointer;
}

.dimension-row:last-child {
  border-bottom: 0;
}

.dimension-row:hover {
  background: var(--surface-hover);
}
.dimension-row.is-current {
  background: var(--sheet-alt);
}

.dimension-name {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.4rem;
  max-width: 100%;
  height: auto;
  min-height: var(--row-h);
  padding-inline: var(--gap-2);
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
