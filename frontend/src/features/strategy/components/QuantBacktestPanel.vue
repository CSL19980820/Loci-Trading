<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { runHorizonBacktest } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import type { HorizonBacktestResult, HorizonStats, StrategyInfo } from '@/shared/types/quant'

import { pnlTone, signed } from '../composables/quantFormat'
import QuantBacktestExtremeTape from './QuantBacktestExtremeTape.vue'

const props = defineProps<{
  strategies: StrategyInfo[]
  loading?: boolean
}>()

const strategySlug = ref('')
const range = ref<[string, string] | null>(null)
const busy = ref(false)
const result = ref<HorizonBacktestResult | null>(null)
const errorText = ref('')
const activePreset = ref<30 | 90 | 180 | null>(90)

const selected = computed(() => props.strategies.find((s) => s.slug === strategySlug.value) ?? null)

const entryLabel = computed(() => {
  const timing = selected.value?.entry_timing || result.value?.entry_timing || ''
  if (timing === 'close') return '尾盘买'
  if (timing === 'next_dip') return '次日低吸'
  if (timing === 'next_open') return '次日开'
  if (timing === 'open') return '开盘买'
  return timing || '—'
})

const entryDetail = computed(() => {
  const timing = selected.value?.entry_timing || result.value?.entry_timing || ''
  if (timing === 'close') return '选股日收盘入场 · T+N 看其后第 N 日最高'
  if (timing === 'next_dip') return '选股日后挂 2% 低吸单 · 成交后看其后第 N 日最高'
  if (timing === 'next_open') return '选股日后一交易日开盘入场 · T+1 约看第 2 日最高'
  if (timing === 'open') return '选股日开盘入场 · T+N 看其后第 N 日最高'
  return '入场时点以战法声明为准'
})

watch(
  () => props.strategies,
  (list) => {
    if (!strategySlug.value && list.length) strategySlug.value = list[0].slug
    if (strategySlug.value && !list.some((s) => s.slug === strategySlug.value)) {
      strategySlug.value = list[0]?.slug ?? ''
    }
  },
  { immediate: true },
)

function iso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function rangeEndingToday(daysBack: number): [string, string] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - daysBack)
  return [iso(start), iso(end)]
}

if (!range.value) range.value = rangeEndingToday(90)

const rangeShortcuts = [
  {
    text: '近一月',
    value: () => {
      const end = new Date()
      const start = new Date()
      start.setDate(start.getDate() - 30)
      return [start, end] as [Date, Date]
    },
  },
  {
    text: '近三月',
    value: () => {
      const end = new Date()
      const start = new Date()
      start.setDate(start.getDate() - 90)
      return [start, end] as [Date, Date]
    },
  },
  {
    text: '近六月',
    value: () => {
      const end = new Date()
      const start = new Date()
      start.setDate(start.getDate() - 180)
      return [start, end] as [Date, Date]
    },
  },
]

function applyPreset(daysBack: 30 | 90 | 180): void {
  activePreset.value = daysBack
  range.value = rangeEndingToday(daysBack)
}

function onRangeChange(): void {
  activePreset.value = null
}

const disabledDate = (date: Date): boolean => {
  const today = new Date()
  today.setHours(23, 59, 59, 999)
  return date.getTime() > today.getTime()
}

async function run(): Promise<void> {
  errorText.value = ''
  if (!strategySlug.value) {
    ElMessage.warning('请先选择战法')
    return
  }
  if (!range.value?.[0] || !range.value?.[1]) {
    ElMessage.warning('请选择回测区间')
    return
  }
  const [start, end] = range.value
  const span = (Date.parse(end) - Date.parse(start)) / 86_400_000
  if (span < 0) {
    ElMessage.warning('结束日不能早于开始日')
    return
  }
  if (span > 186) {
    ElMessage.warning('一次性回测最长约 6 个月（186 天）')
    return
  }

  busy.value = true
  try {
    const next = await runHorizonBacktest({
      strategy: strategySlug.value,
      start,
      end,
      horizons: [1, 3],
    })
    result.value = next
    const n1 = next.horizons.t1?.n ?? 0
    const n3 = next.horizons.t3?.n ?? 0
    if (!n1 && !n3) {
      ElMessage.info('区间内没有可评估的信号事件')
    } else {
      ElMessage.success(`回测完成 · T+1 ${n1} 笔 · T+3 ${n3} 笔`)
    }
  } catch (caught: unknown) {
    errorText.value = toErrorMessage(caught, '回测失败')
    ElMessage.error(errorText.value)
  } finally {
    busy.value = false
  }
}

function statsOf(key: 't1' | 't3'): HorizonStats | null {
  return result.value?.horizons[key] ?? null
}

function skippedText(): string {
  const skipped = result.value?.skipped
  if (!skipped) return ''
  return Object.entries(skipped)
    .filter(([, n]) => n > 0)
    .map(([reason, n]) => `${reason} ${n}`)
    .join(' · ')
}

const resultMeta = computed(() => {
  if (!result.value) return ''
  const start = String((result.value.config?.range as { start?: string } | undefined)?.start || range.value?.[0] || '')
  const end = String((result.value.config?.range as { end?: string } | undefined)?.end || range.value?.[1] || '')
  return `${result.value.strategy} · ${start} — ${end} · ${entryLabel.value}`
})
</script>

<template>
  <div class="bt" v-loading="busy" element-loading-text="正在回测全市场信号，请稍候…">
    <header class="bt-rail">
      <div class="bt-rail__title">
        <h2>战法回测</h2>
        <p>标记日最高 ÷ 选股日收盘 · 最长 6 个月</p>
      </div>
      <el-form class="bt-rail__form" inline @submit.prevent="run">
        <el-form-item label="战法">
          <el-select
            v-model="strategySlug"
            filterable
            placeholder="选择战法"
            style="width: 180px"
            :disabled="loading || !strategies.length || busy"
          >
            <el-option
              v-for="s in strategies"
              :key="s.slug"
              :label="s.name"
              :value="s.slug"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="区间">
          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
            :disabled-date="disabledDate"
            :shortcuts="rangeShortcuts"
            :disabled="busy"
            style="width: 250px"
            @change="onRangeChange"
          />
        </el-form-item>
        <el-form-item>
          <el-button-group class="bt-presets">
            <el-button
              :type="activePreset === 30 ? 'primary' : 'default'"
              :disabled="busy"
              @click="applyPreset(30)"
            >
              近一月
            </el-button>
            <el-button
              :type="activePreset === 90 ? 'primary' : 'default'"
              :disabled="busy"
              @click="applyPreset(90)"
            >
              近三月
            </el-button>
            <el-button
              :type="activePreset === 180 ? 'primary' : 'default'"
              :disabled="busy"
              @click="applyPreset(180)"
            >
              近六月
            </el-button>
          </el-button-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="busy" :disabled="!strategies.length" @click="run">
            跑回测
          </el-button>
        </el-form-item>
      </el-form>
      <p class="bt-rail__meta">
        入场 <strong>{{ entryLabel }}</strong>
        <span class="dot">·</span>
        {{ entryDetail }}
        <span class="dot">·</span>
        与目录胜率跟踪不是同一口径
      </p>
    </header>

    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      closable
      class="bt-alert"
      @close="errorText = ''"
    />

    <EmptyState
      v-if="!result && !busy"
      description="选战法并用近一月 / 三月 / 六月，再跑回测。全市场可能要几十秒，页面会显示加载。"
    />

    <div v-if="result" class="bt-result" :key="resultMeta">
      <p class="bt-result__meta">{{ resultMeta }}</p>

      <div class="bt-horizons">
        <section v-for="key in (['t1', 't3'] as const)" :key="key" class="bt-card">
          <header class="bt-card__head">
            <div>
              <h3>{{ key === 't1' ? 'T+1' : 'T+3' }}</h3>
              <span class="bt-card__n">有效样本 {{ statsOf(key)?.n ?? 0 }}</span>
            </div>
            <template v-if="statsOf(key)">
              <div class="bt-hero">
                <div class="bt-hero__win">
                  <span class="bt-hero__k">胜率</span>
                  <span class="bt-hero__v">{{ statsOf(key)!.win_rate.toFixed(1) }}%</span>
                </div>
                <div class="bt-hero__avg" :class="pnlTone(statsOf(key)!.avg)">
                  <span class="bt-hero__k">平均</span>
                  <span class="bt-hero__v">{{ signed(statsOf(key)!.avg) }}</span>
                </div>
              </div>
            </template>
          </header>

          <EmptyState
            v-if="!statsOf(key)"
            description="该窗口无有效事件（尾部信号或缺行情已剔除）"
          />

          <div v-else class="bt-extremes">
            <QuantBacktestExtremeTape kind="best" :event="statsOf(key)?.best_event" />
            <QuantBacktestExtremeTape kind="worst" :event="statsOf(key)?.worst_event" />
          </div>
        </section>
      </div>

      <p class="bt-footnote">
        样本最佳 / 最差是区间内单笔事件的极值，并标注选股日与标记日；创业板连板两日可接近 +44%，属乐观上沿，不能当成可稳定兑现成交价。
      </p>
      <p v-if="skippedText()" class="bt-skip">跳过：{{ skippedText() }}</p>
    </div>
  </div>
</template>

<style scoped>
.bt {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  min-height: 14rem;
  padding: 0.15rem 0.35rem 0.5rem;
  position: relative;
}
.bt-rail {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius, 8px);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--sheet) 92%, var(--paper)) 0%, var(--sheet) 100%);
}
.bt-rail__title h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 650;
    letter-spacing: 0;
  color: var(--ink);
}
.bt-rail__title p {
  margin: 0.2rem 0 0;
  font-size: 0.8rem;
  color: var(--mist);
}
.bt-rail__form {
  margin: 0;
}
.bt-rail__form :deep(.el-form-item) {
  margin-bottom: 0.35rem;
}
.bt-rail__meta {
  margin: 0;
  font-size: 0.8rem;
  color: var(--mist);
  line-height: 1.45;
}
.bt-rail__meta strong {
  color: var(--ink);
  font-weight: 600;
}
.bt-rail__meta .dot {
  margin: 0 0.35rem;
  opacity: 0.5;
}
.bt-alert {
  margin: 0;
}
.bt-result {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
  animation: bt-in 0.28s ease both;
}
.bt-result__meta {
  margin: 0;
  font: 0.78rem/1.4 var(--mono);
  color: var(--mist);
}
.bt-horizons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.85rem;
  min-height: 0;
}
.bt-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius, 8px);
  background: var(--paper, var(--sheet));
  min-width: 0;
}
.bt-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.65rem 1rem;
}
.bt-card__head h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
    letter-spacing: 0;
}
.bt-card__n {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.78rem;
  color: var(--mist);
}
.bt-hero {
  display: flex;
  gap: 1.1rem;
}
.bt-hero__k {
  display: block;
  font-size: 0.72rem;
  color: var(--mist);
  letter-spacing: 0.04em;
}
.bt-hero__v {
  font: 700 1.45rem/1.1 var(--mono);
  font-variant-numeric: tabular-nums;
    letter-spacing: 0;
  color: var(--ink);
}
.bt-hero__avg.up .bt-hero__v {
  color: var(--up);
}
.bt-hero__avg.down .bt-hero__v {
  color: var(--down);
}
.bt-extremes {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.bt-footnote,
.bt-skip {
  margin: 0;
  font-size: 0.8rem;
  color: var(--mist);
  line-height: 1.45;
}
@keyframes bt-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .bt-result {
    animation: none;
  }
}
@media (max-width: 960px) {
  .bt-horizons {
    grid-template-columns: 1fr;
  }
}
</style>
