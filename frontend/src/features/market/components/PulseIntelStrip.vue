<script setup lang="ts">
import { computed } from 'vue'

import type { IntelBrief, IntelBriefTheme } from '@/shared/api/quant_intel'

const props = defineProps<{
  brief: IntelBrief | null
  loading?: boolean
  error?: string
  /** 嵌在监控带内时去掉外框，由父级统一描边 */
  nested?: boolean
}>()

function fmtCount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return String(Math.round(Number(value)))
}

/** 后端已统一成 0–100；兼容旧缓存里偶发 0–1 比例。 */
function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const pct = n >= 0 && n <= 1.5 ? n * 100 : n
  return `${pct.toFixed(0)}%`
}

function fmtThemeChip(theme: IntelBriefTheme): string {
  const bits = [theme.name]
  if (theme.pct_chg != null && Number.isFinite(Number(theme.pct_chg))) {
    const pct = Number(theme.pct_chg)
    bits.push(`${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`)
  }
  const money = String(theme.main_net_amount_text || '').trim()
  if (money) bits.push(money)
  return bits.join(' ')
}

const themeChips = computed(() =>
  (props.brief?.themes ?? []).slice(0, 4).map((theme) => ({
    key: theme.code || theme.name,
    label: fmtThemeChip(theme),
    up: theme.pct_chg != null ? Number(theme.pct_chg) > 0 : null,
  })),
)

const metaText = computed(() => {
  if (props.loading) return '读取缓存…'
  if (!props.brief?.available) return ''
  const day = props.brief.trade_date
  const fetched = props.brief.fetched_at
    ? ` · 缓存 ${props.brief.fetched_at.replace('T', ' ').slice(0, 16)}`
    : ''
  return `${day}${fetched} · 只读`
})

const showIntelBody = computed(() => Boolean(props.brief?.available))
const promotionLabel = computed(() => {
  const basis = props.brief?.emotion?.promotion_rate_basis
  return basis ? `晋级(${basis})` : '晋级'
})
</script>

<template>
  <section
    class="pulse-intel"
    :class="{ 'pulse-intel--nested': nested, 'pulse-intel--empty': !showIntelBody && !loading }"
    aria-label="短线情报缓存"
  >
    <header class="pulse-intel__head">
      <div class="pulse-intel__brand">
        <strong>短线情报</strong>
      </div>
      <span v-if="metaText" class="pulse-intel__meta">{{ metaText }}</span>
    </header>

    <div v-if="showIntelBody" class="pulse-intel__metrics">
      <div class="pulse-intel__metric">
        <span class="pulse-intel__k">涨停</span>
        <strong class="is-up">{{ fmtCount(brief?.emotion?.limit_up_count) }}</strong>
      </div>
      <div class="pulse-intel__metric">
        <span class="pulse-intel__k">跌停</span>
        <strong class="is-down">{{ fmtCount(brief?.emotion?.limit_down_count) }}</strong>
      </div>
      <div class="pulse-intel__metric">
        <span class="pulse-intel__k">{{ promotionLabel }}</span>
        <strong>{{ fmtPct(brief?.emotion?.promotion_rate) }}</strong>
      </div>
      <div class="pulse-intel__metric">
        <span class="pulse-intel__k">炸板</span>
        <strong>{{ fmtPct(brief?.emotion?.broken_rate) }}</strong>
      </div>
      <div class="pulse-intel__metric">
        <span class="pulse-intel__k">高度</span>
        <strong>{{ fmtCount(brief?.ladder?.height) }}</strong>
      </div>
      <div
        v-if="brief?.emotion?.advancers != null || brief?.emotion?.decliners != null"
        class="pulse-intel__metric"
      >
        <span class="pulse-intel__k">涨跌家</span>
        <strong>
          <span class="is-up">{{ fmtCount(brief?.emotion?.advancers) }}</span>
          <span class="pulse-intel__slash">/</span>
          <span class="is-down">{{ fmtCount(brief?.emotion?.decliners) }}</span>
        </strong>
      </div>
    </div>

    <div v-if="showIntelBody && themeChips.length" class="pulse-intel__themes" aria-label="题材资金">
      <span class="pulse-intel__k">题材</span>
      <div class="pulse-intel__chips">
        <el-tag
          v-for="chip in themeChips"
          :key="chip.key"
          size="small"
          effect="plain"
          :type="chip.up === true ? 'danger' : chip.up === false ? 'success' : 'info'"
        >
          {{ chip.label }}
        </el-tag>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pulse-intel {
  flex-shrink: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  padding: 0.45rem 0.75rem 0.55rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.pulse-intel--nested {
  border: none;
  border-radius: 0;
  background: transparent;
  padding: 0.4rem 0.75rem 0.45rem;
}

.pulse-intel--empty {
  padding-bottom: 0.35rem;
}

.pulse-intel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.75rem;
}

.pulse-intel__brand {
  display: inline-flex;
  align-items: center;
}

.pulse-intel__head strong {
  font-size: 0.82rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ink);
}

.pulse-intel__meta {
  font-size: 0.72rem;
  color: var(--mist);
  font-variant-numeric: tabular-nums;
}

.pulse-intel__metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
}

.pulse-intel__metric {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  min-width: 4.2rem;
}

.pulse-intel__k {
  font-size: 0.7rem;
  color: var(--mist);
  flex-shrink: 0;
}

.pulse-intel__metric strong {
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono, ui-monospace, monospace);
  font-weight: 600;
}

.pulse-intel__slash {
  margin: 0 0.1rem;
  color: var(--mist);
  font-weight: 500;
}

.pulse-intel__themes {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}

.pulse-intel__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  min-width: 0;
}

.is-up {
  color: var(--up);
}

.is-down {
  color: var(--down);
}
</style>
