<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  fetchLanesCatalog,
  patchLaneProvider,
  probeLanes,
  speedtestLane,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type {
  DataLane,
  LaneProbeResult,
  LaneProvider,
  LaneSpeedTestResult,
  LanesSummary,
} from '@/shared/types/quant'
import { firstLine, formatRtt, formatThroughput } from '../composables/opsLabels'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{
  'summary-changed': [summary: LanesSummary | null]
}>()

const { busy, notice, guard } = useOpsFeedback()

const dataLanes = ref<DataLane[]>([])
const laneProviders = ref<LaneProvider[]>([])
const lanesSummary = ref<LanesSummary | null>(null)
const selectedLaneId = ref('hist_daily')
const probeResults = ref<LaneProbeResult[]>([])
const speedResults = ref<LaneSpeedTestResult[]>([])
const boardMode = ref<'probe' | 'speedtest'>('probe')

type BoardRow = {
  id: string
  label: string
  rtt_ms: number | null
  rows: number | null
  mb_per_s: number | null
  ok: boolean
  error: string | null
  missingHint: string
  isWinner: boolean
}

const selectedLaneLabel = computed(() => laneLabel(selectedLaneId.value))

const boardRows = computed((): BoardRow[] => {
  const laneId = selectedLaneId.value
  const labelOf = (id: string, fallback?: string) =>
    fallback || laneProviders.value.find((p) => p.id === id)?.label || id

  const missingOf = (row: {
    missing_fields?: string[]
    extra?: Record<string, unknown>
  }): string[] => {
    if (Array.isArray(row.missing_fields) && row.missing_fields.length) return row.missing_fields
    const extra = row.extra?.missing_fields
    return Array.isArray(extra) ? (extra as string[]) : []
  }

  let raw: BoardRow[] = []
  if (boardMode.value === 'speedtest' && selectedLaneId.value === 'hist_daily') {
    raw = speedResults.value.map((row) => {
      const missing = missingOf(row)
      return {
        id: row.adapter_id,
        label: labelOf(row.adapter_id, row.label),
        rtt_ms: row.elapsed_ms,
        rows: row.rows,
        mb_per_s: row.mb_per_s,
        ok: row.ok,
        error: row.error ?? null,
        missingHint: missing.length ? `缺 ${missing.join('、')}` : '',
        isWinner: false,
      }
    })
  } else {
    raw = probeResults.value
      .filter((row) => row.lane === laneId && !row.unsupported)
      .map((row) => {
        const missing = missingOf(row)
        return {
          id: row.adapter_id,
          label: labelOf(row.adapter_id, row.label),
          rtt_ms: row.rtt_ms,
          rows: row.rows ?? null,
          mb_per_s: null,
          ok: row.ok,
          error: row.error ?? null,
          missingHint: missing.length ? `缺 ${missing.join('、')}` : '',
          isWinner: false,
        }
      })
  }

  const eligible = raw.filter((row) => row.ok && !row.missingHint)
  if (eligible.length) {
    const best = Math.min(...eligible.map((row) => row.rtt_ms ?? Number.POSITIVE_INFINITY))
    for (const row of raw) {
      if (row.ok && !row.missingHint && row.rtt_ms === best) row.isWinner = true
    }
  }
  return raw
})

function laneLabel(laneId: string): string {
  return dataLanes.value.find((lane) => lane.id === laneId)?.label ?? laneId
}

function probeHitsFor(adapterId: string): LaneProbeResult[] {
  return probeResults.value.filter((row) => row.adapter_id === adapterId && !row.unsupported)
}

function providerStatusText(adapterId: string): string {
  const hits = probeHitsFor(adapterId)
  if (!hits.length) return '尚未探测'
  if (hits.every((row) => row.ok)) return '通'
  if (hits.some((row) => row.ok)) return '部分通'
  return '失败'
}

function providerStatusClass(adapterId: string): string {
  const text = providerStatusText(adapterId)
  if (text === '通' || text === '部分通') return 'tag'
  return 'chip muted-chip'
}

function mergeProbeResults(incoming: LaneProbeResult[]): void {
  const byKey = new Map<string, LaneProbeResult>()
  for (const row of probeResults.value) {
    byKey.set(`${row.adapter_id}:${row.lane}`, row)
  }
  for (const row of incoming) {
    byKey.set(`${row.adapter_id}:${row.lane}`, row)
  }
  probeResults.value = [...byKey.values()]
}

function refreshSummaryFromProbes(): void {
  const byLane = new Map<string, LaneProbeResult[]>()
  for (const row of probeResults.value) {
    if (row.unsupported) continue
    const list = byLane.get(row.lane) ?? []
    list.push(row)
    byLane.set(row.lane, list)
  }
  let ok = 0
  let degraded = 0
  let down = 0
  for (const [, rows] of byLane) {
    if (rows.some((r) => r.ok)) {
      if (rows.every((r) => r.ok)) ok += 1
      else degraded += 1
    } else if (rows.length) {
      down += 1
    }
  }
  if (ok + degraded + down > 0) {
    lanesSummary.value = { ok, degraded, down }
    emit('summary-changed', lanesSummary.value)
  }
}

async function load(): Promise<void> {
  const lanes = await fetchLanesCatalog().catch(() => null)
  if (!lanes) return
  dataLanes.value = lanes.lanes ?? []
  laneProviders.value = lanes.providers ?? []
  lanesSummary.value = lanes.summary ?? null
  emit('summary-changed', lanesSummary.value)
  if (!selectedLaneId.value && dataLanes.value.length) {
    selectedLaneId.value = dataLanes.value[0].id
  } else if (
    dataLanes.value.length &&
    !dataLanes.value.some((lane) => lane.id === selectedLaneId.value)
  ) {
    selectedLaneId.value = dataLanes.value[0].id
  }
}

async function probeAllLanes(): Promise<void> {
  const result = await guard(() => probeLanes(null))
  if (!result) return
  mergeProbeResults(result.results ?? [])
  boardMode.value = 'probe'
  refreshSummaryFromProbes()
  notice.value = `已探测 ${result.results?.length ?? 0} 条源×类目`
}

async function probeSelectedLane(): Promise<void> {
  const lane = selectedLaneId.value
  if (!lane) return
  const result = await guard(() => probeLanes(lane))
  if (!result) return
  mergeProbeResults(result.results ?? [])
  boardMode.value = 'probe'
  refreshSummaryFromProbes()
  notice.value = `已探测「${laneLabel(lane)}」· ${result.results?.length ?? 0} 个源`
}

async function probeProvider(item: LaneProvider): Promise<void> {
  const lanes = item.lanes?.length ? item.lanes : [null]
  const collected: LaneProbeResult[] = []
  const result = await guard(async () => {
    for (const lane of lanes) {
      const resp = await probeLanes(lane, item.id)
      collected.push(...(resp.results ?? []))
    }
    return collected
  })
  if (!result) return
  mergeProbeResults(result)
  boardMode.value = 'probe'
  if (item.lanes?.[0]) selectedLaneId.value = item.lanes[0]
  refreshSummaryFromProbes()
  const okCount = result.filter((row) => row.ok).length
  notice.value = `${item.label} · ${okCount}/${result.length} 通`
}

async function toggleProvider(item: LaneProvider, enabled: boolean): Promise<void> {
  const saved = await guard(() => patchLaneProvider(item.id, enabled))
  if (!saved) return
  const idx = laneProviders.value.findIndex((p) => p.id === item.id)
  if (idx >= 0) {
    laneProviders.value[idx] = { ...laneProviders.value[idx], enabled: saved.enabled }
  }
  notice.value = saved.enabled ? `已启用 ${saved.label}` : `已停用 ${saved.label}`
}

async function runSpeedtest(): Promise<void> {
  if (selectedLaneId.value !== 'hist_daily') return
  const result = await guard(() => speedtestLane('hist_daily', '600519'))
  if (!result) return
  const rows = result.results ?? []
  speedResults.value = rows
  boardMode.value = 'speedtest'
  notice.value = `下载测速完成 · ${rows.length} 个源`
}

defineExpose({ load, lanesSummary })
</script>

<template>
  <Sheet title="可接入 API" :chip="laneProviders.length" margin>
    <template #actions>
      <el-button type="primary" link :disabled="busy" @click="probeAllLanes">全部探测</el-button>
    </template>

    <div v-if="laneProviders.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>名称</th>
            <th>支持类目</th>
            <th>状态</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in laneProviders" :key="item.id">
            <td>
              <strong>{{ item.label }}</strong>
              <p v-if="item.description" class="reason">{{ item.description }}</p>
            </td>
            <td>
              <span v-for="laneId in item.lanes" :key="laneId" class="tag lane-chip">
                {{ laneLabel(laneId) }}
              </span>
            </td>
            <td>
              <span :class="providerStatusClass(item.id)">{{ providerStatusText(item.id) }}</span>
              <span v-if="item.enabled === false" class="chip muted-chip">已停用</span>
            </td>
            <td class="r">
              <el-switch
                :model-value="item.enabled !== false"
                :disabled="busy"
                size="small"
                inline-prompt
                active-text="开"
                inactive-text="关"
                @change="(v: boolean) => toggleProvider(item, v)"
              />
              <el-button size="small" text :disabled="busy" @click="probeProvider(item)">
                测这家
              </el-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      description="尚未加载 API 目录"
      reason="后端线路接口未就绪，或刷新失败"
      eta="点右上角刷新重试"
    />
  </Sheet>

  <Sheet title="类目比速" :chip="selectedLaneLabel">
    <template #actions>
      <el-button type="primary" link :disabled="busy || !selectedLaneId" @click="probeSelectedLane">
        探测本类
      </el-button>
      <el-tooltip
        :disabled="selectedLaneId === 'hist_daily'"
        content="下载测速仅支持历史日 K"
        placement="top"
      >
        <span>
          <el-button
            type="primary"
            link
            :disabled="busy || selectedLaneId !== 'hist_daily'"
            @click="runSpeedtest"
          >
            下载测速
          </el-button>
        </span>
      </el-tooltip>
    </template>

    <div class="lane-pills">
      <button
        v-for="lane in dataLanes"
        :key="lane.id"
        type="button"
        class="lane-pill"
        :class="{ active: selectedLaneId === lane.id }"
        :disabled="busy"
        @click="selectedLaneId = lane.id"
      >
        {{ lane.label }}
        <span v-if="lane.required" class="lane-pill-req">必</span>
      </button>
    </div>
    <p v-if="selectedLaneId !== 'hist_daily'" class="form-hint">
      下载测速仅对「历史日 K」开放；本类可用「探测本类」看连通与 RTT。
    </p>

    <div v-if="boardRows.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>源</th>
            <th class="r">RTT</th>
            <th class="r">行数</th>
            <th class="r">吞吐</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in boardRows" :key="row.id" :class="{ 'lane-winner': row.isWinner }">
            <td>
              <strong>{{ row.label }}</strong>
              <span v-if="row.isWinner" class="tag winner-tag">赢家</span>
            </td>
            <td class="r mono">{{ formatRtt(row.rtt_ms) }}</td>
            <td class="r mono">{{ row.rows == null ? '—' : row.rows }}</td>
            <td class="r mono">{{ formatThroughput(row.mb_per_s) }}</td>
            <td :class="row.ok ? '' : 'tone-down'">
              {{ row.ok ? '通' : '失败' }}
              <span v-if="row.error" class="dim">{{ firstLine(row.error) }}</span>
              <span v-else-if="row.missingHint" class="dim">{{ row.missingHint }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      description="尚未探测"
      reason="还没有对本类跑过探测或测速"
      eta="点「探测本类」或「下载测速」"
    >
      <el-button type="primary" :disabled="busy || !selectedLaneId" @click="probeSelectedLane">
        探测本类
      </el-button>
    </EmptyState>
  </Sheet>
</template>

<style scoped>
.lane-chip {
  margin: 0 0.25rem 0.25rem 0;
  display: inline-block;
}

.lane-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.75rem 0.85rem 0.35rem;
}

.lane-pill {
  appearance: none;
  border: 1px solid var(--rule);
  background: var(--sheet);
  color: var(--ink);
  font: inherit;
  font-size: 0.82rem;
  padding: 0.28rem 0.7rem;
  border-radius: var(--radius);
  cursor: pointer;
}

.lane-pill:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.lane-pill.active {
  border-color: color-mix(in srgb, var(--seal) 45%, var(--rule));
  background: color-mix(in srgb, var(--seal-soft) 60%, var(--sheet));
  color: var(--ink);
  font-weight: 600;
}

.lane-pill-req {
  margin-left: 0.25rem;
  font-size: 0.7rem;
  color: var(--mist);
}

.lane-winner td {
  background: color-mix(in srgb, var(--seal-soft) 45%, transparent);
}

.winner-tag {
  margin-left: 0.35rem;
  background: color-mix(in srgb, var(--seal) 18%, #e8edf3);
  color: var(--seal);
}
</style>
