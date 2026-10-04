/** 数据源控制台：源目录 + 逐工具启停 + 连通探测读数。数字全部来自后端。 */
import { computed, onScopeDispose, ref } from 'vue'

import {
  fetchLanesCatalog,
  patchLaneProvider,
  probeLanes,
  saveLanePolicy,
  speedtestLane,
} from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  DataLane,
  LanePolicy,
  LanePolicyMode,
  LaneProbeResponse,
  LaneProbeResult,
  LaneProvider,
  LaneSpeedTestResponse,
  LaneSpeedTestResult,
} from '@/shared/types/quant'

/** 一次「这家源 × 这个工具」的实测读数。 */
export type ProbeCell = {
  ok: boolean
  rttMs: number | null
  rows: number | null
  error: string
  unsupported: boolean
  /** probe=小样本连通；download=历史日 K 整段下载 */
  kind: 'probe' | 'download'
}

export type SourceTool = {
  lane: string
  label: string
  required: boolean
  /** 源总开关与逐工具开关都开才算可用 */
  enabled: boolean
  /** 生效顺位（1 起）；不在生效列表里为 null */
  order: number | null
  probe: ProbeCell | null
}

export type SourceRow = {
  id: string
  label: string
  description: string
  baseUrl: string
  enabled: boolean
  masterEnabled: boolean
  tools: SourceTool[]
  enabledCount: number
  disabledCount: number
  /** 保留接入的诊断字段 */
  interfaceCount?: number
  /** 接入类型兼容标识 */
  interfaceOnly: boolean
  /** 已探测工具的中位耗时 */
  medianRttMs: number | null
  probedCount: number
  failedCount: number
}

export type LaneSource = {
  id: string
  label: string
  enabled: boolean
  masterEnabled: boolean
  /** 整源被停用（不只是这条线路），在这里开会连带把源开回来 */
  masterOff: boolean
  order: number | null
  probe: ProbeCell | null
}

export type LaneRow = {
  lane: string
  label: string
  required: boolean
  mode: LanePolicyMode
  providerId: string | null
  fallback: boolean
  sources: LaneSource[]
  effectiveCount: number
  supportsDownloadTest: boolean
}

/** 探测/测速/启停都用它标记「哪一处正在忙」，按钮各自转圈。 */
export type BusyKey = string

function cellKey(providerId: string, lane: string): string {
  return `${providerId}:${lane}`
}

function median(values: number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2
}

export function useDataSources() {
  const lanes = ref<DataLane[]>([])
  const providers = ref<LaneProvider[]>([])
  const policies = ref<LanePolicy[]>([])
  const cells = ref<Record<string, ProbeCell>>({})
  const loading = ref(false)
  const error = ref('')
  const notice = ref('')
  const busyKey = ref<BusyKey>('')
  const code = ref('600519')
  const runs = ref<1 | 2 | 3>(1)
  let loadVersion = 0

  onScopeDispose(() => {
    loadVersion += 1
  })

  const laneLabel = computed(() => new Map(lanes.value.map((lane) => [lane.id, lane.label])))
  const laneRequired = computed(() => new Map(lanes.value.map((lane) => [lane.id, lane.required])))
  const policyByLane = computed(() => new Map(policies.value.map((item) => [item.lane, item])))

  /** 只统计数据源家数，不把工具条数混进来。 */
  const stats = computed(() => {
    const total = sources.value.length
    const enabled = sources.value.filter((row) => row.enabled).length
    return { total, enabled, disabled: total - enabled }
  })

  function toolOf(provider: LaneProvider, lane: string): SourceTool {
    const muted = (provider.disabled_lanes ?? []).includes(lane)
    const effective = policyByLane.value.get(lane)?.effective_provider_ids ?? []
    const index = effective.indexOf(provider.id)
    return {
      lane,
      label: laneLabel.value.get(lane) ?? lane,
      required: laneRequired.value.get(lane) ?? false,
      enabled: provider.enabled !== false && !muted,
      order: index < 0 ? null : index + 1,
      probe: cells.value[cellKey(provider.id, lane)] ?? null,
    }
  }

  const sources = computed<SourceRow[]>(() => {
    const wired = providers.value.map((provider) => {
      const tools = (provider.lanes ?? []).map((lane) => toolOf(provider, lane))
      const probed = tools.filter((tool) => tool.probe)
      return {
        id: provider.id,
        label: provider.label,
        description: provider.description ?? '',
        baseUrl: provider.base_url ?? '',
        enabled: provider.enabled !== false,
        masterEnabled: provider.enabled !== false,
        tools,
        enabledCount: tools.filter((tool) => tool.enabled).length,
        disabledCount: tools.filter((tool) => !tool.enabled).length,
        interfaceOnly: false,
        medianRttMs: median(
          probed
            .filter((tool) => tool.probe?.ok && tool.probe.rttMs != null)
            .map((tool) => Number(tool.probe?.rttMs)),
        ),
        probedCount: probed.length,
        failedCount: probed.filter((tool) => tool.probe && !tool.probe.ok).length,
      }
    })
    return wired
  })

  const laneRows = computed<LaneRow[]>(() =>
    lanes.value.map((lane) => {
      const policy = policyByLane.value.get(lane.id)
      const effective = policy?.effective_provider_ids ?? []
      const laneSources: LaneSource[] = providers.value
        .filter((provider) => (provider.lanes ?? []).includes(lane.id))
        .map((provider) => {
          const tool = toolOf(provider, lane.id)
          return {
            id: provider.id,
            label: provider.label,
            enabled: tool.enabled,
            masterEnabled: provider.enabled !== false,
            masterOff: provider.enabled === false,
            order: tool.order,
            probe: tool.probe,
          }
        })
        .sort((left, right) => (left.order ?? 99) - (right.order ?? 99))
      return {
        lane: lane.id,
        label: lane.label,
        required: lane.required,
        mode: policy?.mode ?? 'auto',
        providerId: policy?.provider_id ?? null,
        fallback: policy?.fallback ?? false,
        sources: laneSources,
        effectiveCount: effective.length,
        supportsDownloadTest: lane.id === 'hist_daily',
      }
    }),
  )

  /** 必需线路被关空了：同步仍会跑，但一定失败，得红字顶在页首。 */
  const brokenRequiredLanes = computed(() =>
    laneRows.value.filter((row) => row.required && row.effectiveCount === 0),
  )

  async function guard<T>(key: BusyKey, task: () => Promise<T>, done = ''): Promise<T | null> {
    busyKey.value = key
    error.value = ''
    notice.value = ''
    try {
      const result = await task()
      if (done) notice.value = done
      return result
    } catch (caught: unknown) {
      error.value = toErrorMessage(caught, '请求失败')
      return null
    } finally {
      busyKey.value = ''
    }
  }

  async function load(): Promise<void> {
    const version = ++loadVersion
    loading.value = true
    try {
      const catalog = await fetchLanesCatalog()
      if (version !== loadVersion) return
      lanes.value = catalog.lanes ?? []
      providers.value = catalog.providers ?? []
      policies.value = catalog.policies ?? []
      error.value = ''
    } catch (caught: unknown) {
      if (version !== loadVersion) return
      error.value = toErrorMessage(caught, '加载数据源目录失败')
    } finally {
      if (version === loadVersion) loading.value = false
    }
  }

  function validCode(): string | null {
    const normalized = code.value.trim()
    if (!/^\d{6}$/.test(normalized)) {
      error.value = '样例代码必须为 6 位数字。'
      return null
    }
    code.value = normalized
    return normalized
  }

  function absorb(
    response: LaneProbeResponse | LaneSpeedTestResponse,
    kind: ProbeCell['kind'],
    fallbackLane = '',
  ): number {
    const next = { ...cells.value }
    let count = 0
    const rows: (LaneProbeResult | LaneSpeedTestResult)[] = response.results ?? []
    for (const row of rows) {
      const provider = row.adapter_id
      const lane = ('lane' in row && row.lane) || fallbackLane
      if (!provider || !lane) continue
      const rtt = 'rtt_ms' in row ? row.rtt_ms : row.elapsed_ms
      next[cellKey(provider, lane)] = {
        ok: Boolean(row.ok),
        rttMs: rtt == null ? null : Number(rtt),
        rows: row.rows ?? null,
        error: row.error ?? '',
        unsupported: 'unsupported' in row ? Boolean(row.unsupported) : false,
        kind,
      }
      count += 1
    }
    cells.value = next
    return count
  }

  async function probeSource(providerId: string): Promise<void> {
    const isMcp = providerId.startsWith('mcp:')
    // MCP 情报探测只握手，不依赖样例代码；行情源仍要 6 位代码
    let target = '600519'
    if (!isMcp) {
      const code = validCode()
      if (!code) return
      target = code
    }
    const label =
      providers.value.find((row) => row.id === providerId)?.label ?? providerId
    const response = await guard(`source:${providerId}`, () =>
      probeLanes(null, providerId, { code: target, runs: isMcp ? 1 : runs.value }),
    )
    if (!response) return
    const count = absorb(response, 'probe')
    if (isMcp) {
      const hit = response.results?.[0]
      notice.value = hit
        ? `${label}：${hit.ok ? '连通正常' : '连通失败'}${hit.rtt_ms != null ? ` · ${Math.round(Number(hit.rtt_ms))}ms` : ''}`
        : `${label}：无探测结果`
      return
    }
    notice.value = count ? `${label}：已测 ${count} 个工具` : `${label} 没有可测的工具`
  }

  async function probeLane(lane: string): Promise<void> {
    const target = validCode()
    if (!target) return
    const label = laneLabel.value.get(lane) ?? lane
    const response = await guard(`lane:${lane}`, () =>
      probeLanes(lane, null, { code: target, runs: runs.value }),
    )
    if (!response) return
    const count = absorb(response, 'probe', lane)
    notice.value = count ? `${label}：已测 ${count} 家源` : `${label} 当前没有启用的源`
  }

  async function probeAll(): Promise<void> {
    const target = validCode()
    if (!target) return
    // 按线路逐个探测并即时回填，避免一次巨型请求堵死 UI；单线路后端另有墙钟超时。
    const response = await guard('all', async () => {
      let total = 0
      for (const row of laneRows.value) {
        if (!row.sources.some((item) => item.enabled)) continue
        const part = await probeLanes(row.lane, null, { code: target, runs: runs.value })
        total += absorb(part, 'probe', row.lane)
      }
      return total
    })
    if (response == null) return
    notice.value = response ? `全量探测完成：${response} 条读数` : '没有启用的源可探测'
  }

  async function downloadTest(lane: string): Promise<void> {
    const target = validCode()
    if (!target) return
    const response = await guard(`speed:${lane}`, () =>
      speedtestLane(lane, target, runs.value),
    )
    if (!response) return
    const count = absorb(response, 'download', response.lane ?? lane)
    notice.value = count ? `下载测速完成：${count} 家源` : '没有启用的源可测速'
  }

  async function toggleSource(providerId: string, enabled: boolean): Promise<void> {
    if (providerId.startsWith('mcp:')) {
      notice.value = '外部 MCP 情报请在运维 → MCP 页配置 Key 与到期日'
      return
    }
    const label = providers.value.find((row) => row.id === providerId)?.label ?? providerId
    const saved = await guard(`toggle:${providerId}`, () => patchLaneProvider(providerId, enabled))
    if (!saved) return
    await load()
    notice.value = `${label} 已${enabled ? '启用' : '停用'}`
  }

  async function toggleTool(providerId: string, lane: string, enabled: boolean): Promise<void> {
    if (providerId.startsWith('mcp:')) {
      notice.value = '外部 MCP 情报请在运维 → MCP 页配置 Key 与到期日'
      return
    }
    const provider = providers.value.find((row) => row.id === providerId)
    const label = provider?.label ?? providerId
    const laneName = laneLabel.value.get(lane) ?? lane
    // 整源关着时只开单条线路等于没开：连带把源总开关拨回来，否则开关看着像失灵
    const wakeSource = enabled && provider?.enabled === false
    const saved = await guard(`toggle:${providerId}:${lane}`, async () => {
      if (wakeSource) await patchLaneProvider(providerId, true)
      return patchLaneProvider(providerId, enabled, lane)
    })
    if (!saved) return
    await load()
    notice.value = wakeSource
      ? `${label} 已整源启用，${laneName}现在可用`
      : `${label} 的${laneName}已${enabled ? '启用' : '停用'}`
  }

  async function savePolicy(
    lane: string,
    policy: { mode: LanePolicyMode; provider_id?: string | null; fallback: boolean },
  ): Promise<void> {
    const laneName = laneLabel.value.get(lane) ?? lane
    const saved = await guard(`policy:${lane}`, () => saveLanePolicy(lane, policy))
    if (!saved) return
    await load()
    notice.value = `${laneName} 选源已保存`
  }

  return {
    lanes,
    providers,
    cells,
    loading,
    error,
    notice,
    busyKey,
    code,
    runs,
    stats,
    sources,
    laneRows,
    brokenRequiredLanes,
    load,
    probeSource,
    probeLane,
    probeAll,
    downloadTest,
    toggleSource,
    toggleTool,
    savePolicy,
  }
}
