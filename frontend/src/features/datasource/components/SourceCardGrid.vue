<script setup lang="ts">
import LatencyMeter from './LatencyMeter.vue'
import type { SourceRow } from '../composables/useDataSources'

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
</script>

<template>
  <div class="src-grid">
    <article
      v-for="row in rows"
      :key="row.id"
      class="src-card"
      :class="{ 'src-card--off': !row.enabled }"
    >
      <header class="src-card__head">
        <el-tooltip :content="row.description || '本机内置源，无额外说明'" placement="top-start">
          <div class="src-card__name">
            <strong>{{ row.label }}</strong>
            <code>{{ row.id }}</code>
          </div>
        </el-tooltip>
        <el-tag v-if="row.interfaceOnly" size="small" type="info" effect="plain">接口源</el-tag>
        <el-switch
          v-else
          :model-value="row.masterEnabled"
          :loading="toggling(row.id)"
          :aria-label="`启用 ${row.label}`"
          @change="(next: string | number | boolean) => emit('toggle', { id: row.id, enabled: Boolean(next) })"
        />
      </header>

      <ul v-if="row.tools.length" class="tool-rail" :aria-label="`${row.label} 的工具`">
        <li
          v-for="tool in row.tools"
          :key="tool.lane"
          class="tool-chip"
          :class="{ 'tool-chip--off': !tool.enabled, 'tool-chip--bad': tool.probe && !tool.probe.ok }"
        >
          <span class="tool-chip__label">{{ tool.label }}</span>
          <span v-if="!tool.enabled" class="tool-chip__mark">停</span>
          <span v-else-if="tool.probe" class="tool-chip__mark">
            {{ tool.probe.ok ? `${Math.round(tool.probe.rttMs ?? 0)}ms` : '失败' }}
          </span>
        </li>
      </ul>

      <footer class="src-card__foot">
        <p class="src-card__counts">
          <template v-if="row.tools.length">
            线路 <b>{{ row.tools.length }}</b>
            <span class="sep">·</span>启用 <b>{{ row.enabledCount }}</b>
            <span class="sep">·</span>停用 <b>{{ row.disabledCount }}</b>
          </template>
          <template v-if="row.interfaceCount != null">
            <span v-if="row.tools.length" class="sep">·</span>
            接口 <b>{{ row.interfaceCount }}</b>
          </template>
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
          <el-button
            v-if="row.interfaceCount"
            size="small"
            @click="emit('interfaces', row.id)"
          >
            接口
          </el-button>
          <el-button
            v-if="row.tools.length"
            size="small"
            :loading="probing(row.id)"
            @click="emit('probe', row.id)"
          >
            探测
          </el-button>
          <el-button size="small" type="primary" plain @click="emit('open', row.id)">
            详情
          </el-button>
        </div>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.src-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
  gap: var(--gap-2);
  align-content: start;
}

.src-card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  min-width: 0;
  padding: var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
}

.src-card--off {
  background: var(--surface-canvas);
}

.src-card--off .src-card__name strong {
  color: var(--mist);
}

.src-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
}

.src-card__name {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
  cursor: help;
}

.src-card__name strong {
  font-family: var(--font);
  font-size: var(--fs-title);
  line-height: 1.2;
}

.src-card__name code {
  font: var(--fs-aux) var(--mono);
  overflow-wrap: anywhere;
  color: var(--mist);
}

.tool-rail {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.tool-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 0.3rem;
  padding: 0.12rem 0.42rem;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: var(--paper);
  font-size: var(--fs-aux);
  color: var(--ink);
}

.tool-chip--off {
  border-style: dashed;
  background: transparent;
  color: var(--mist);
}

.tool-chip--bad {
  border-color: var(--warn);
  background: var(--warn-soft);
}

.tool-chip__mark {
  font: 600 0.7rem var(--mono);
  color: var(--mist);
}

.src-card__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.6rem;
  margin-top: auto;
  padding-top: 0.45rem;
  border-top: 1px solid color-mix(in oklab, var(--rule) 60%, transparent);
}

.src-card__counts,
.src-card__idle {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
}

.src-card__counts b {
  font: 600 var(--fs-body) var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.sep {
  margin: 0 0.28rem;
  color: var(--rule);
}

.src-card__lat {
  flex: 1 1 5rem;
  min-width: 5rem;
}

.src-card__actions {
  display: flex;
  gap: 0.35rem;
  margin-left: auto;
}
</style>
