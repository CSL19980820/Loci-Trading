<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  formatTokenCount,
  type ContextUsageSnapshot,
} from '../assistantContextUsage'

const props = defineProps<{
  usage: ContextUsageSnapshot
  /** 后端 context_compacted 后展示；无事件勿传 */
  compactNotice?: string
}>()

const open = ref(false)

const title = computed(() => `${props.usage.percent}% 已用`)
const summary = computed(
  () => `~${formatTokenCount(props.usage.used)} / ${formatTokenCount(props.usage.window)} Tokens`,
)
const pressureHint = computed(() => {
  const pct = props.usage.percent
  if (pct >= 90) return '接近上限：精简追问，或新开会话，避免模型静默截断。'
  if (pct >= 70) return '上下文偏满：长工具回执可新开一轮，保留关键结论。'
  return ''
})
const compactHint = computed(() => String(props.compactNotice || '').trim())

const ringDash = computed(() => {
  const pct = Math.max(0, Math.min(100, props.usage.percent)) / 100
  const circumference = 2 * Math.PI * 5.5
  return {
    dash: circumference,
    offset: circumference * (1 - pct),
    // 三档走语义色：此前健康用品牌色、警告用「品牌色掺琥珀」，
    // 换琥珀主题后两者算出来几乎同色，70% 这道警戒线会直接消失。
    tone: pct >= 90 ? 'var(--warn-ink)' : pct >= 70 ? 'var(--warn)' : 'var(--mist)',
  }
})

const barSegments = computed(() => {
  const window = Math.max(1, props.usage.window)
  return props.usage.segments.map((segment) => ({
    ...segment,
    width: `${Math.max(0.4, (segment.tokens / window) * 100)}%`,
  }))
})

function close(): void {
  open.value = false
}
</script>

<template>
  <div class="ctx-usage" data-testid="assistant-context-usage">
    <!--
      受控 visible 不要再给 reference 绑 toggle：与 trigger=click 叠在一起会同一次点击开→关闪退。
    -->
    <el-popover
      v-model:visible="open"
      placement="top-end"
      :width="320"
      trigger="click"
      popper-class="ctx-usage-popper"
    >
      <template #reference>
        <el-button
          class="ctx-usage__trigger"
          text
          data-testid="assistant-context-usage-trigger"
          :aria-expanded="open"
          aria-haspopup="dialog"
          :aria-label="`上下文用量 ${title}`"
        >
          <span class="ctx-usage__ring" aria-hidden="true">
            <svg class="ctx-usage__ring-svg" viewBox="0 0 14 14" focusable="false">
              <circle
                class="ctx-usage__ring-track"
                cx="7"
                cy="7"
                r="5.5"
                fill="none"
                stroke-width="2"
              />
              <circle
                class="ctx-usage__ring-value"
                cx="7"
                cy="7"
                r="5.5"
                fill="none"
                stroke-width="2"
                :stroke="ringDash.tone"
                :stroke-dasharray="ringDash.dash"
                :stroke-dashoffset="ringDash.offset"
                stroke-linecap="round"
                transform="rotate(-90 7 7)"
              />
            </svg>
          </span>
          <span class="ctx-usage__pct">{{ usage.percent }}%</span>
        </el-button>
      </template>

      <div class="ctx-usage__panel" role="dialog" aria-label="上下文用量">
        <header class="ctx-usage__head">
          <h3 class="ctx-usage__title">{{ title }}</h3>
          <el-tooltip content="粗估喂模上下文（汉字≈1、其它≈4字/token），非供应商计费账单" placement="top">
            <span class="ctx-usage__summary mono" tabindex="0">{{ summary }}</span>
          </el-tooltip>
          <el-button
            class="ctx-usage__close"
            text
            circle
            size="small"
            aria-label="关闭"
            @click="close"
          >
            ×
          </el-button>
        </header>
        <p v-if="compactHint" class="ctx-usage__compact" role="status" data-testid="assistant-context-compacted">{{ compactHint }}</p>
        <p v-if="pressureHint" class="ctx-usage__pressure" role="status">{{ pressureHint }}</p>
        <div class="ctx-usage__bar" aria-hidden="true">
          <span
            v-for="segment in barSegments"
            :key="segment.kind"
            class="ctx-usage__bar-seg"
            :style="{ width: segment.width, background: segment.color }"
            :title="`${segment.label} ${formatTokenCount(segment.tokens)}`"
          />
          <span
            class="ctx-usage__bar-free"
            :style="{ width: `${Math.max(0, (usage.remaining / Math.max(1, usage.window)) * 100)}%` }"
          />
        </div>
        <ul class="ctx-usage__list" role="list">
          <li
            v-for="segment in usage.segments"
            :key="segment.kind"
            class="ctx-usage__row"
          >
            <span class="ctx-usage__swatch" :style="{ background: segment.color }" aria-hidden="true" />
            <span class="ctx-usage__label">{{ segment.label }}</span>
            <span class="ctx-usage__tokens mono">{{ formatTokenCount(segment.tokens) }}</span>
          </li>
        </ul>
      </div>
    </el-popover>
  </div>
</template>

<style scoped>
.ctx-usage {
  display: inline-flex;
  align-items: center;
}

.ctx-usage__trigger {
  display: inline-flex !important;
  align-items: center;
  gap: .35rem;
  height: var(--ctl-h) !important;
  padding: 0 .35rem !important;
  border-radius: var(--ai-r-chip) !important;
  color: var(--mist) !important;
}

.ctx-usage__trigger:hover,
.ctx-usage__trigger:focus-visible {
  color: var(--ink) !important;
  background: var(--seal-soft) !important;
}

.ctx-usage__ring {
  position: relative;
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
}

.ctx-usage__ring-svg {
  display: block;
  width: 14px;
  height: 14px;
}

.ctx-usage__ring-track {
  stroke: color-mix(in oklab, var(--rule) 80%, transparent);
}

.ctx-usage__ring-value {
  transition: stroke-dashoffset .2s ease;
}

.ctx-usage__pct {
  font-size: var(--ai-fs-meta);
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  letter-spacing: .02em;
}

.ctx-usage__panel {
  display: flex;
  flex-direction: column;
  gap: .55rem;
  min-width: 0;
}

.ctx-usage__head {
  display: flex;
  align-items: center;
  gap: .5rem;
}

.ctx-usage__title {
  margin: 0;
  flex: 0 0 auto;
  font-size: var(--ai-fs-title);
  font-weight: 650;
  color: var(--ink);
  letter-spacing: -.01em;
}

.ctx-usage__summary {
  margin: 0 0 0 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.ctx-usage__close {
  flex: 0 0 auto;
  margin: -.2rem -.2rem 0 0 !important;
  color: var(--mist) !important;
  font-size: var(--ai-fs-title) !important;
}

.ctx-usage__pressure {
  margin: 0;
  padding: .35rem .45rem;
  border-radius: var(--ai-r-card);
  font-size: var(--ai-fs-aux);
  line-height: 1.4;
  color: color-mix(in oklab, var(--warn) 85%, var(--ink));
  background: color-mix(in oklab, var(--warn) 12%, transparent);
  border: 1px solid color-mix(in oklab, var(--warn) 28%, transparent);
}

.ctx-usage__compact {
  margin: 0;
  padding: .35rem .45rem;
  border-radius: var(--ai-r-card);
  font-size: var(--ai-fs-aux);
  line-height: 1.4;
  color: color-mix(in oklab, var(--info) 90%, var(--ink));
  background: color-mix(in oklab, var(--info) 10%, transparent);
  border: 1px solid color-mix(in oklab, var(--info) 24%, transparent);
}

.ctx-usage__bar {
  display: flex;
  width: 100%;
  height: 8px;
  overflow: hidden;
  border-radius: var(--ai-r-pill);
  background: color-mix(in oklab, var(--rule) 55%, transparent);
}

.ctx-usage__bar-seg {
  display: block;
  height: 100%;
  min-width: 2px;
}

.ctx-usage__bar-free {
  display: block;
  height: 100%;
  background: transparent;
}

.ctx-usage__list {
  display: flex;
  flex-direction: column;
  gap: .35rem;
  margin: .15rem 0 0;
  padding: 0;
  list-style: none;
}

.ctx-usage__row {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: .55rem;
  align-items: center;
}

.ctx-usage__swatch {
  width: 8px;
  height: 8px;
  border-radius: var(--ai-r-chip);
}

.ctx-usage__label {
  min-width: 0;
  color: var(--ink);
  font-size: var(--ai-fs-body);
}

.ctx-usage__tokens {
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  font-variant-numeric: tabular-nums;
}

.mono {
  font-family: var(--mono);
}
.ctx-usage__row { padding-block: var(--gap-1); border-bottom: 1px solid var(--rule-soft); }
.ctx-usage__panel { max-height: 70dvh; overflow: auto; scrollbar-width: thin; }
.ctx-usage__trigger:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
@media (prefers-reduced-motion: reduce) { .ctx-usage__ring-value { transition: none; } }
</style>
