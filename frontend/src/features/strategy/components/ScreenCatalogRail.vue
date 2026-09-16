<script setup lang="ts">
import { computed, ref } from 'vue'
import { Cpu, Search, SetUp } from '@element-plus/icons-vue'

import { pct } from '@/shared/lib/format'
import { sampleConfidence, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

import type { ScreenCatalogItem } from '../composables/useScreenCatalog'

const props = defineProps<{
  rows: ScreenCatalogItem[]
  selectedId: string
  kindFilter: 'all' | 'engine' | 'skill'
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  'update:kindFilter': [value: 'all' | 'engine' | 'skill']
}>()

const query = ref('')

const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.rows
  return props.rows.filter(
    (row) =>
      row.name.toLowerCase().includes(q) ||
      row.slug.toLowerCase().includes(q),
  )
})

/** 战法目录用一位小数，够看趋势即可。 */
function fmtPct(value: number | null | undefined): string {
  return pct(value, 1)
}

/** 样本不足时不刷文案，右侧只留 —；够数才出胜率·均收益。 */
function hasCredibleStats(row: ScreenCatalogItem): boolean {
  return sampleConfidence(row.sample) !== 'low' && row.winRate != null
}
</script>

<template>
  <div class="catalog-rail strategy-surface" aria-label="选股能力目录">
    <div class="catalog-rail__tools">
      <el-radio-group
        :model-value="kindFilter"
        aria-label="选股能力类型"
        size="small"
        @update:model-value="emit('update:kindFilter', $event as 'all' | 'engine' | 'skill')"
      >
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="engine">战法</el-radio-button>
        <el-radio-button value="skill">技能</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="query"
        clearable
        size="small"
        placeholder="搜名称"
        :prefix-icon="Search"
        aria-label="搜索战法或技能"
      />
    </div>

    <el-skeleton v-if="loading && !rows.length" :rows="6" animated />
    <EmptyState v-else-if="!visible.length" :description="query ? '没有匹配项' : '暂无战法或技能'" :reason="query ? '清空搜索后重试' : '前往工坊创建'" />
    <ul v-else class="catalog-rail__list">
      <li
        v-for="row in visible"
        :key="row.id"
        :class="{ 'is-selected': row.id === selectedId, 'is-disabled': row.kind === 'skill' && !row.enabled }"
      >
        <el-button
          class="catalog-row"
          text
          :aria-pressed="row.id === selectedId"
          :aria-label="`${row.name}，${row.kind === 'engine' ? '战法' : '技能'}${row.kind === 'skill' && !row.enabled ? '，已停用' : ''}`"
          @click="emit('select', row.id)"
        >
          <span class="catalog-row__main">
            <el-tag
              size="small"
              type="info"
              effect="plain"
            >
              <el-icon aria-hidden="true"><component :is="row.kind === 'engine' ? SetUp : Cpu" /></el-icon>
              {{ row.kind === 'engine' ? '战法' : '技能' }}
            </el-tag>
            <strong class="catalog-row__name">{{ row.name }}</strong>
          </span>
          <span
            v-if="hasCredibleStats(row)"
            class="catalog-row__stat mono"
            :class="winRateDisplayTone(row.winRate, row.sample)"
          >
            {{ winRateText(row.winRate) }}
            <span class="mist">{{ fmtPct(row.avgReturn) }}</span>
          </span>
          <span v-else class="catalog-row__stat mono mist">—</span>
        </el-button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.catalog-rail {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  height: 100%;
  min-height: 0;
  padding: 0.55rem 0.45rem;
}

.catalog-rail__tools {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex-shrink: 0;
}

.catalog-rail__list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow: auto;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.catalog-row {
  width: 100%;
  height: auto !important;
  min-height: 0 !important;
  padding: 0.4rem 0.45rem !important;
  justify-content: space-between;
  align-items: center;
  text-align: left;
  border: 1px solid transparent;
  border-radius: var(--radius);
  white-space: nowrap;
  gap: 0.45rem;
}

.catalog-row__main {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
  flex: 1;
}

.catalog-row__name {
  font-family: var(--font);
  font-size: 0.88rem;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-row__stat {
  flex-shrink: 0;
  font-size: var(--fs-kicker);
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
}

.mist {
  color: var(--mist);
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.is-selected .catalog-row {
  background: color-mix(in oklab, var(--seal-soft) 55%, var(--sheet));
  border-color: color-mix(in oklab, var(--seal) 35%, var(--rule));
}

.is-disabled {
  opacity: 0.55;
}

.wr-muted {
  color: var(--mist);
}
.wr-mid {
  color: var(--muted);
}
.wr-high {
  color: var(--up);
}
.wr-low {
  color: var(--down);
}
</style>
<style scoped src="./StrategySurfaces.css"></style>
