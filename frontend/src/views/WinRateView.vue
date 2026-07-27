<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>胜率统计</h1>
      <span v-if="summary.length" class="muted mono">{{ summary.length }} 个战法</span>
    </div>
    <div class="toolbar-actions">
      <select v-model="granularity" @change="loadTrend">
        <option value="month">按月</option>
        <option value="week">按周</option>
      </select>
      <button class="quiet-button" type="button" :disabled="busy" @click="reload">刷新</button>
    </div>
  </header>

  <p v-if="error" class="error-banner" role="alert"><span>{{ error }}</span></p>

  <!-- 综合胜率汇总 -->
  <section class="panel mb">
    <div class="panel-bar"><h2>综合胜率（全时段）</h2></div>
    <div v-if="summary.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>战法</th>
            <th class="r">复盘总数</th>
            <th class="r">盈利次数</th>
            <th class="r">综合胜率</th>
            <th class="r">平均收益</th>
            <th>最近复盘</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in summary" :key="row.strategy_tag">
            <td><strong>{{ row.strategy_tag }}</strong></td>
            <td class="r mono">{{ row.total }}</td>
            <td class="r mono">{{ row.wins }}</td>
            <td class="r mono">
              <span :class="winRateTone(row.win_rate)">
                <strong>{{ row.win_rate !== null ? `${row.win_rate}%` : '—' }}</strong>
              </span>
            </td>
            <td class="r mono" :class="row.avg_return !== null ? (row.avg_return >= 0 ? 'tone-up' : 'tone-down') : ''">
              {{ row.avg_return !== null ? `${row.avg_return >= 0 ? '+' : ''}${row.avg_return.toFixed(2)}%` : '—' }}
            </td>
            <td class="mono dim">{{ row.last_reviewed || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty pad">尚无复盘数据（需要在复盘记录中填写 return_pct）。</p>
  </section>

  <!-- 趋势图 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>胜率趋势</h2>
      <div class="toolbar-actions">
        <span v-for="tag in allTags" :key="tag" class="legend-item">
          <button
            type="button"
            class="legend-btn"
            :class="{ 'legend-active': activeTags.has(tag) }"
            @click="toggleTag(tag)"
          >
            {{ tag }}
          </button>
        </span>
      </div>
    </div>

    <div v-if="chartData.length" class="trend-chart-wrap">
      <div class="trend-table-wrap">
        <table class="dense">
          <thead>
            <tr>
              <th>{{ granularity === 'month' ? '月份' : '周' }}</th>
              <th v-for="tag in activeTags" :key="tag" class="r">{{ tag }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in trendRows" :key="row.period">
              <td class="mono">{{ row.period }}</td>
              <td v-for="tag in activeTags" :key="tag" class="r mono">
                <span :class="winRateTone(row.byTag[tag]?.win_rate ?? null)">
                  {{ row.byTag[tag]?.win_rate !== undefined ? `${row.byTag[tag].win_rate}%` : '—' }}
                </span>
                <span class="dim"> ({{ row.byTag[tag]?.total ?? 0 }})</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <p v-else class="empty pad">
      {{ busy ? '加载中…' : '无趋势数据。' }}
    </p>
    <p class="form-hint">
      括号内为该周期的复盘总笔数。胜率 = 正收益复盘次数 / 总复盘次数，数据来源于复盘记录的 return_pct 字段。
      笔数少于 5 时仅供参考。
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { CapabilityUnavailableError, getWinRateSummary, getWinRateTrend } from '@/api/quant'
import type { WinRateSummary, WinRateTrendPoint } from '@/types/quant'

const summary = ref<WinRateSummary[]>([])
const chartData = ref<WinRateTrendPoint[]>([])
const granularity = ref<'month' | 'week'>('month')
const busy = ref(false)
const error = ref('')

const allTags = computed(() => [...new Set(summary.value.map((row) => row.strategy_tag))])
const activeTags = ref<Set<string>>(new Set())

function toggleTag(tag: string): void {
  const next = new Set(activeTags.value)
  if (next.has(tag)) {
    next.delete(tag)
  } else {
    next.add(tag)
  }
  activeTags.value = next
}

/** 把一维列表变成 [{period, byTag: {tag → point}}] 便于表格渲染 */
const trendRows = computed(() => {
  const periods = [...new Set(chartData.value.map((p) => p.period))].sort()
  return periods.map((period) => {
    const byTag: Record<string, WinRateTrendPoint> = {}
    for (const point of chartData.value) {
      if (point.period === period && activeTags.value.has(point.strategy_tag)) {
        byTag[point.strategy_tag] = point
      }
    }
    return { period, byTag }
  }).reverse() // 最新在上
})

function winRateTone(rate: number | null): string {
  if (rate === null) return ''
  if (rate >= 60) return 'tone-up'
  if (rate >= 45) return ''
  return 'tone-down'
}

async function loadTrend(): Promise<void> {
  if (!allTags.value.length) return
  try {
    chartData.value = await getWinRateTrend({
      granularity: granularity.value,
      tags: allTags.value.join(','),
    })
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载趋势失败'
  }
}

async function reload(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    summary.value = await getWinRateSummary()
    activeTags.value = new Set(allTags.value)
    await loadTrend()
  } catch (e: unknown) {
    error.value = e instanceof CapabilityUnavailableError ? e.message : (e instanceof Error ? e.message : '加载失败')
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.legend-item { display: inline-flex; }
.legend-btn {
  padding: 2px 10px;
  border: 1px solid var(--line-2);
  border-radius: 12px;
  background: var(--panel-2);
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
  transition: background 0.15s;
}
.legend-btn.legend-active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.trend-chart-wrap { overflow-x: auto; }
.trend-table-wrap { min-width: 400px; }
</style>
