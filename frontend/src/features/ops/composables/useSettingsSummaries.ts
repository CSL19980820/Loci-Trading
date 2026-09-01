import { onScopeDispose, reactive } from 'vue'

import {
  getDataLocation,
  getDesktopPrefs,
  getMarketSyncSettings,
  getMcpServers,
  getProviders,
  getSharePackStatus,
  getWecomSettings,
} from '@/shared/api/quant'
import { APPEARANCE_OPTIONS, getStoredAppearance } from '@/shared/lib/theme'
import { APP_VERSION } from '@/shared/lib/release'

import type { RailMark } from '../components/SettingsRail.vue'
import { formatBytes } from './opsLabels'

export type OpsTab = 'mcp' | 'llm' | 'system' | 'signals' | 'pack'

export type RailSummary = { tail: string; state: RailMark }

const EMPTY: Record<OpsTab, RailSummary> = {
  mcp: { tail: '—', state: 'idle' },
  llm: { tail: '—', state: 'idle' },
  // 信号规则的读数由 SignalRulesTab 自己回传（见 OpsView 的 @summary）：
  // 规则接口只有那一处在用，没必要为了 rail 上一行小字再全局拉一次。
  signals: { tail: '—', state: 'idle' },
  system: { tail: '—', state: 'idle' },
  pack: { tail: '—', state: 'idle' },
}

function appearanceTail(): string {
  const id = getStoredAppearance()
  return APPEARANCE_OPTIONS.find((o) => o.id === id)?.label ?? id
}

export function useSettingsSummaries() {
  const summaries = reactive<Record<OpsTab, RailSummary>>({ ...EMPTY })
  let refreshVersion = 0

  onScopeDispose(() => {
    refreshVersion += 1
  })

  async function refresh(): Promise<void> {
    const version = ++refreshVersion
    const results = await Promise.allSettled([
      getMcpServers(),
      getProviders(),
      getDataLocation(),
      getMarketSyncSettings(),
      getWecomSettings(),
      getDesktopPrefs(),
      getSharePackStatus(),
    ])
    if (version !== refreshVersion) return

    const mcp = results[0].status === 'fulfilled' ? results[0].value : []
    const providers = results[1].status === 'fulfilled' ? results[1].value : []
    const dataLoc = results[2].status === 'fulfilled' ? results[2].value : null
    const sync = results[3].status === 'fulfilled' ? results[3].value : null
    const wecom = results[4].status === 'fulfilled' ? results[4].value : null
    void (results[5].status === 'fulfilled' ? results[5].value : null)
    const pack = results[6].status === 'fulfilled' ? results[6].value : null

    const mcpActive = mcp.filter((s) => s.is_active).length
    Object.assign(summaries.mcp, {
      tail: mcp.length ? `${mcp.length} 台` : '未配',
      state: mcp.length === 0 ? 'idle' : mcpActive > 0 ? 'ok' : 'idle',
    })

    const def = providers.find((p) => p.is_default)
    Object.assign(summaries.llm, {
      tail: providers.length ? (def?.name ?? `${providers.length} 家`) : '未配',
      state: providers.length ? 'ok' : 'idle',
    })

    // 系统联摘要：版本号优先露出；同步时刻 / 目录体积作次级
    let systemTail = `v${APP_VERSION}`
    let systemState: RailMark = 'ok'
    if (sync) {
      const on = sync.enabled_intraday || sync.enabled_eod
      const eod = `${String(sync.eod_hour).padStart(2, '0')}:${String(sync.eod_minute).padStart(2, '0')}`
      if (on) {
        systemTail = `v${APP_VERSION} · ${sync.enabled_eod ? eod : `每 ${sync.interval_minutes} 分`}`
        systemState = 'ok'
      } else if (dataLoc) {
        systemTail = `v${APP_VERSION} · ${formatBytes(dataLoc.market_bytes)}`
        systemState = dataLoc.needed_bootstrap ? 'idle' : 'ok'
      } else {
        systemTail = `v${APP_VERSION}`
        systemState = 'idle'
      }
    } else if (dataLoc) {
      systemTail = `v${APP_VERSION} · ${formatBytes(dataLoc.market_bytes)}`
      systemState = dataLoc.needed_bootstrap ? 'idle' : 'ok'
    }
    if (wecom && !wecom.configured && systemState === 'ok' && sync && !(sync.enabled_intraday || sync.enabled_eod)) {
      systemState = 'idle'
    }
    Object.assign(summaries.system, { tail: systemTail, state: systemState })

    if (pack) {
      Object.assign(summaries.pack, {
        tail: pack.can_pack ? `v${pack.version}` : '未编译',
        state: pack.can_pack ? 'ok' : 'idle',
      })
    } else {
      Object.assign(summaries.pack, { tail: '—', state: 'idle' })
    }
  }

  function refreshAppearanceLocal(): void {
    // 外观变更时不冲掉版本前缀
    if (!summaries.system.tail.startsWith('v')) {
      summaries.system.tail = `v${APP_VERSION} · ${appearanceTail()}`
    }
    summaries.system.state = 'ok'
  }

  return { summaries, refresh, refreshAppearanceLocal }
}
