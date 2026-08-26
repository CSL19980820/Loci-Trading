<script setup lang="ts">
defineProps<{
  isCatchup: boolean
  coverageLast: string
  expectedLast: string
  rangeLabel: string
  lagLabel: string
  running: boolean
  isDone: boolean
  isError: boolean
  leadText: string
  dataDirLabel: string
  error: string
  percent: number
  detail: string
  reportSummary: string
}>()
</script>

<template>
  <div class="boot-body">
    <div class="boot-split">
      <dl class="boot-facts" aria-label="补齐日期明细">
        <div class="boot-fact">
          <dt>库内最新</dt>
          <dd class="mono">{{ isCatchup ? coverageLast || '—' : coverageLast || '暂无日 K' }}</dd>
        </div>
        <div v-if="isCatchup || expectedLast" class="boot-fact">
          <dt>{{ isCatchup ? '将补区间' : '目标覆盖至' }}</dt>
          <dd class="mono boot-fact-range">
            {{ isCatchup ? rangeLabel || expectedLast || '—' : expectedLast || '—' }}
          </dd>
        </div>
        <div v-if="isCatchup && lagLabel" class="boot-fact">
          <dt>落后</dt>
          <dd>{{ lagLabel }}</dd>
        </div>
        <div v-if="!isCatchup" class="boot-fact">
          <dt>范围</dt>
          <dd>全市场历史日线</dd>
        </div>
      </dl>

      <div class="boot-pane">
        <template v-if="!running && !isDone">
          <p class="boot-lead">{{ leadText }}</p>
          <p class="boot-hint">
            <template v-if="isCatchup">补齐期间请保持窗口打开；关闭可能中断同步。</template>
            <template v-else>
              全市场首次约 10–40 分钟，写入
              <span class="boot-path">{{ dataDirLabel }}</span>
            </template>
          </p>
          <div v-if="error" class="boot-err" role="alert">
            <strong class="boot-err-label">无法继续</strong>
            <p class="boot-err-text">{{ error }}</p>
          </div>
        </template>

        <template v-else>
          <p class="boot-lead">{{ leadText }}</p>
          <div
            class="seal-meter"
            :class="{ 'seal-meter--done': isDone, 'seal-meter--err': isError }"
            aria-label="同步进度"
          >
            <div class="seal-meter__track">
              <div
                class="seal-meter__fill"
                :style="{ width: `${Math.min(100, Math.max(0, percent))}%` }"
              />
            </div>
            <span class="seal-meter__pct">{{ Math.round(percent) }}%</span>
          </div>
          <p v-if="detail" class="boot-hint mono">{{ detail }}</p>
          <p v-if="isDone && reportSummary" class="boot-hint mono">{{ reportSummary }}</p>
          <div v-if="isError && error" class="boot-err" role="alert">
            <strong class="boot-err-label">同步中断</strong>
            <p class="boot-err-text">{{ error }}</p>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.boot-body {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.15rem 0 0.25rem;
}

.boot-split {
  display: grid;
  grid-template-columns: minmax(10.5rem, 0.95fr) minmax(0, 1.25fr);
  gap: 0.85rem;
  align-items: stretch;
}

.boot-facts {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  margin: 0;
  padding: 0.75rem 0.85rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--paper) 70%, var(--sheet));
}

.boot-fact {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.boot-fact dt {
  margin: 0;
  color: var(--mist);
  font: 500 0.7rem/1.2 var(--mono);
  letter-spacing: 0.06em;
}

.boot-fact dd {
  margin: 0;
  color: var(--ink);
  font: 550 0.92rem/1.25 var(--font);
  word-break: break-all;
}

.boot-fact-range {
  font-weight: 650;
  color: var(--seal-ink);
}

.boot-pane {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.55rem;
  min-width: 0;
  padding: 0.15rem 0.1rem;
}

.boot-lead {
  margin: 0;
  color: var(--ink);
  font: 450 0.92rem/1.5 var(--font);
}

@media (max-width: 560px) {
  .boot-split {
    grid-template-columns: 1fr;
  }
}

.boot-hint {
  margin: 0;
  color: var(--mist);
  font: 0.82rem/1.5 var(--font);
}

.boot-path {
  font-family: var(--mono);
  font-size: 0.8em;
  word-break: break-all;
  color: var(--ink);
}

.boot-err {
  padding: 0.7rem 0.85rem;
  border: 1px solid color-mix(in srgb, var(--seal) 28%, var(--rule));
  border-radius: var(--radius);
  background: var(--seal-soft);
}

.boot-err-label {
  display: block;
  margin-bottom: 0.25rem;
  color: var(--seal-ink);
  font: 650 0.78rem/1.2 var(--font);
  letter-spacing: 0.04em;
}

.boot-err-text {
  margin: 0;
  color: var(--ink);
  font: 0.84rem/1.45 var(--font);
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}
</style>
