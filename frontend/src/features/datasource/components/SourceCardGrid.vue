<script setup lang="ts">
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { Activity, ArrowUpRight, ListTree } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Switch } from '@/shared/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import LatencyMeter from './LatencyMeter.vue'
import type { SourceRow } from '../composables/useDataSources'

/**
 * 数据源卡（Vercel Integrations 一路）：字母方块 + 名称 / id 两行 + 总开关；
 * 中段是线路 chip（停用虚线、失败琥珀底、成功带毫秒），底部延迟表 + 三个动作。
 * 整卡可点进详情。
 */
const props = defineProps<{
  rows: SourceRow[]
  /** 正在忙的动作键，来自 useDataSources().busyKey */
  busyKey: string
}>()

const emit = defineEmits<{
  open: [id: string]
  probe: [id: string]
  toggle: [payload: { id: string; enabled: boolean }]
  /** 去「按接口」看这家源的 AkShare 接口 */
  interfaces: [id: string]
}>()

function probing(id: string): boolean {
  return props.busyKey === `source:${id}`
}

function toggling(id: string): boolean {
  return props.busyKey === `toggle:${id}`
}

function initial(row: SourceRow): string {
  return (row.label || row.id || '?').trim().slice(0, 1).toUpperCase()
}

function health(row: SourceRow): 'ok' | 'bad' | 'idle' | 'off' {
  if (!row.enabled) return 'off'
  if (row.interfaceOnly) return 'idle'
  if (row.medianRttMs != null) return row.failedCount === 0 ? 'ok' : 'bad'
  if (row.probedCount) return 'bad'
  return 'idle'
}
</script>

<template>
  <div class="src-grid">
    <article
      v-for="row in rows"
      :key="row.id"
      class="src-card"
      :class="[`is-${health(row)}`, { 'src-card--off': !row.enabled }]"
      role="button"
      tabindex="0"
      :aria-label="`${row.label} · 详情`"
      @click="emit('open', row.id)"
      @keydown.enter.self.prevent="emit('open', row.id)"
      @keydown.space.self.prevent="emit('open', row.id)"
    >
      <header class="src-card__head">
        <span class="src-card__mark" aria-hidden="true">
          {{ initial(row) }}
          <i class="src-card__dot" />
        </span>
        <Tooltip>
          <TooltipTrigger as-child>
            <div class="src-card__name">
              <strong>{{ row.label }}</strong>
              <code>{{ row.id }}</code>
            </div>
          </TooltipTrigger>
          <TooltipContent side="top" align="start">{{ row.description || '本机内置源，无额外说明' }}</TooltipContent>
        </Tooltip>
        <UiBadge v-if="row.interfaceOnly" variant="info">接口源</UiBadge>
        <span v-else class="src-card__switch" @click.stop>
          <Switch v-if="!visitor"
            :model-value="row.masterEnabled"
            :disabled="toggling(row.id)"
            :aria-label="`启用 ${row.label}`"
            @update:model-value="(next) => emit('toggle', { id: row.id, enabled: Boolean(next) })"
          />
        </span>
      </header>

      <ul v-if="row.tools.length" class="tool-rail" :aria-label="`${row.label} 的工具`">
        <li
          v-for="tool in row.tools"
          :key="tool.lane"
          class="tool-chip"
          :class="{ 'tool-chip--off': !tool.enabled, 'tool-chip--bad': tool.probe && !tool.probe.ok, 'tool-chip--ok': tool.probe?.ok }"
        >
          <span class="tool-chip__label">{{ tool.label }}</span>
          <span v-if="!tool.enabled" class="tool-chip__mark">停</span>
          <span v-else-if="tool.probe" class="tool-chip__mark">
            {{ tool.probe.ok ? `${Math.round(tool.probe.rttMs ?? 0)}ms` : '失败' }}
          </span>
        </li>
      </ul>

      <footer class="src-card__foot" @click.stop>
        <p class="src-card__counts">
          <template v-if="row.tools.length">
            <span>线路 <b>{{ row.tools.length }}</b></span>
            <span>启用 <b>{{ row.enabledCount }}</b></span>
            <span v-if="row.disabledCount">停用 <b>{{ row.disabledCount }}</b></span>
          </template>
          <span v-if="row.interfaceCount != null">接口 <b>{{ row.interfaceCount }}</b></span>
        </p>
        <LatencyMeter
          v-if="row.medianRttMs != null"
          class="src-card__lat"
          :ms="row.medianRttMs"
          :ok="row.failedCount === 0"
        />
        <p v-else-if="!row.interfaceOnly" class="src-card__idle">
          {{ row.probedCount ? '全部工具探测失败' : '未探测' }}
        </p>
        <div class="src-card__actions">
          <Button access="read" v-if="row.interfaceCount" variant="ghost" size="sm" @click="emit('interfaces', row.id)">
            <ListTree />
            接口
          </Button>
          <Button v-if="row.tools.length" variant="outline" size="sm" :disabled="probing(row.id)" @click="emit('probe', row.id)">
            <Activity :class="probing(row.id) ? 'animate-pulse' : ''" />
            探测
          </Button>
          <Button access="read" variant="ghost" size="sm" @click="emit('open', row.id)">
            详情
            <ArrowUpRight />
          </Button>
        </div>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.src-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: var(--gap-3);
  align-content: start;
}

.src-card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  min-width: 0;
  padding: var(--gap-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.src-card:hover {
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
}

.src-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.src-card--off {
  background: var(--surface-canvas);
  box-shadow: none;
}

.src-card--off .src-card__name strong {
  color: var(--text-tertiary);
}

.src-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-3);
}

.src-card__mark {
  position: relative;
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 700;
}

.src-card__dot {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 10px;
  height: 10px;
  border: 2px solid var(--surface);
  border-radius: 50%;
  background: var(--border-strong);
}

.src-card.is-ok .src-card__dot {
  background: var(--ok);
}

.src-card.is-bad .src-card__dot {
  background: var(--warn);
}

.src-card.is-off .src-card__dot {
  background: var(--text-disabled);
}

.src-card__name {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.src-card__name strong {
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.25;
}

.src-card__name code {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  overflow-wrap: anywhere;
}

.src-card__switch {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  margin-top: 4px;
}

.tool-rail {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.tool-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 2px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-kicker);
  font-weight: 500;
}

.tool-chip--ok {
  border-color: color-mix(in oklab, var(--ok) 30%, var(--border-subtle));
}

.tool-chip--off {
  border-style: dashed;
  background: transparent;
  color: var(--text-tertiary);
}

.tool-chip--bad {
  border-color: color-mix(in oklab, var(--warn) 45%, var(--border-subtle));
  background: var(--warn-soft);
  color: var(--warn-ink);
}

.tool-chip__mark {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.tool-chip--ok .tool-chip__mark {
  color: var(--ok);
}

.src-card__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  margin-top: auto;
  padding-top: var(--gap-3);
  border-top: 1px solid var(--border-subtle);
}

.src-card__counts,
.src-card__idle {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px var(--gap-2);
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.src-card__counts b {
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.src-card__lat {
  flex: 1 1 5rem;
  min-width: 5rem;
}

.src-card__actions {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

@media (prefers-reduced-motion: reduce) {
  .src-card {
    transition: none;
  }
}
</style>
