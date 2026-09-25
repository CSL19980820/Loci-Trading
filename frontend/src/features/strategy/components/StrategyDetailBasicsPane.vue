<script setup lang="ts">
/** 战法概览：说明 → 买入说明 → 默认参数 → 所需字段 → 回测口径。 */
import { computed } from 'vue'

import type { StrategyInfo } from '@/shared/types/quant'
import {
  backtestConfigEntries,
  strategyFieldRows,
  strategyParamRows,
} from './strategyDetailFormat'

const props = defineProps<{
  strategy: StrategyInfo | null
}>()

const paramRows = computed(() => strategyParamRows(props.strategy))
const fieldRows = computed(() => strategyFieldRows(props.strategy))
const backtestRows = computed(() => backtestConfigEntries(props.strategy?.backtest_config))
</script>

<template>
  <div class="ov">
    <p class="ov__desc" :class="{ 'is-empty': !strategy?.description }">{{ strategy?.description || '—' }}</p>

    <section v-if="strategy?.entry_instructions" class="ov__callout" aria-label="买入说明">
      <span class="ov__kicker">买入</span>
      <p>{{ strategy.entry_instructions }}</p>
    </section>

    <section v-if="paramRows.length" class="ov__block" aria-label="默认参数">
      <h4 class="ov__title">默认参数<span>{{ paramRows.length }}</span></h4>
      <dl class="ov__params">
        <div v-for="row in paramRows" :key="row.key" class="ov__param">
          <dt :title="row.key">{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
    </section>

    <section v-if="fieldRows.length" class="ov__block" aria-label="所需字段">
      <h4 class="ov__title">所需字段<span>{{ fieldRows.length }}</span></h4>
      <ul class="ov__chips">
        <li v-for="row in fieldRows" :key="row.key" class="ov__chip">
          {{ row.label }}<code>{{ row.key }}</code>
        </li>
      </ul>
    </section>

    <section v-if="backtestRows.length" class="ov__block" aria-label="回测口径">
      <h4 class="ov__title">回测口径</h4>
      <dl class="ov__bt">
        <div v-for="row in backtestRows" :key="row.key">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.ov {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.ov__desc {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-body);
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.ov__desc.is-empty {
  color: var(--text-tertiary);
}

.ov__callout {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-lg);
  background: color-mix(in oklab, var(--seal) 6%, var(--surface-sunken));
}

.ov__callout p {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.ov__kicker {
  flex: none;
  height: 20px;
  padding: 0 7px;
  border-radius: var(--radius-xs);
  background: var(--seal);
  color: var(--on-primary);
  font-size: var(--fs-kicker);
  font-weight: 600;
  line-height: 20px;
}

.ov__block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.ov__title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.ov__title span {
  color: var(--text-tertiary);
  font: 500 var(--fs-kicker) / 1 var(--mono);
}

.ov__params {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
  margin: 0;
}

.ov__param {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface);
}

.ov__param dt {
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ov__param dd {
  margin: 0;
  color: var(--text-primary);
  font: 600 var(--fs-title) / 1.2 var(--mono);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.ov__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.ov__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-primary);
  font-size: var(--fs-aux);
}

.ov__chip code {
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1 var(--mono);
}

.ov__bt {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0;
  margin: 0;
  border-top: 1px solid var(--border-subtle);
}

.ov__bt > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.ov__bt > div:nth-child(odd) {
  padding-right: 16px;
}

.ov__bt dt {
  flex: none;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.ov__bt dd {
  min-width: 0;
  margin: 0;
  color: var(--text-primary);
  font: var(--fs-aux) / 1.4 var(--mono);
  text-align: right;
  overflow-wrap: anywhere;
}
</style>
