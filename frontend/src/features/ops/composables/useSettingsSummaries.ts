import { getCurrentScope, onScopeDispose, reactive } from 'vue'
import { getMarketSyncSettings, getMcpServers, getProviders } from '@/shared/api/quant'
import { APPEARANCE_OPTIONS, getStoredAppearance } from '@/shared/lib/theme'
import { APP_VERSION } from '@/shared/lib/release'
import type { RailMark } from '../components/SettingsRail.vue'

export type OpsTab = 'mcp' | 'llm' | 'system' | 'retention'
export type RailSummary = { tail: string; state: RailMark }
const EMPTY: Record<OpsTab, RailSummary> = {
  retention: { tail: '保留策略', state: 'idle' },
  mcp: { tail: '—', state: 'idle' }, llm: { tail: '—', state: 'idle' },
  system: { tail: '—', state: 'idle' },
}

export function useSettingsSummaries() {
  // Component-local state: a previous account/tenant must not seed another rail.
  const summaries = reactive<Record<OpsTab, RailSummary>>(structuredClone(EMPTY))
  let refreshVersion = 0
  if (getCurrentScope()) onScopeDispose(() => { refreshVersion++ })

  async function refresh(): Promise<void> {
    const version = ++refreshVersion
    async function settle<T>(request: Promise<T>, key: OpsTab, apply: (result: T) => void): Promise<void> {
      try { const value = await request; if (version === refreshVersion) apply(value) }
      catch { if (version === refreshVersion) Object.assign(summaries[key], { tail: '读取失败', state: 'bad' }) }
    }
    // No database counts, desktop preferences or notification configuration for a rail label.
    // Each result is applied independently; the slowest request never hides the others.
    await Promise.all([
      settle(getMcpServers(), 'mcp', mcp => Object.assign(summaries.mcp, {
        tail: mcp.length ? `${mcp.length} 台` : '未配',
        state: mcp.some(s => s.is_active) ? 'ok' : 'idle',
      })),
      settle(getProviders(), 'llm', providers => Object.assign(summaries.llm, {
        tail: providers.length ? (providers.find(p => p.is_default)?.name ?? `${providers.length} 家`) : '未配',
        state: providers.length ? 'ok' : 'idle',
      })),
      settle(getMarketSyncSettings(), 'system', sync => {
        const on = sync && (sync.enabled_intraday || sync.enabled_eod)
        const eod = sync ? `${String(sync.eod_hour).padStart(2, '0')}:${String(sync.eod_minute).padStart(2, '0')}` : ''
        Object.assign(summaries.system, {
          tail: on ? `v${APP_VERSION} · ${sync.enabled_eod ? eod : `每 ${sync.interval_minutes} 分`}` : `v${APP_VERSION}`,
          state: on ? 'ok' : 'idle',
        })
      }),
    ])
  }
  function refreshAppearanceLocal(): void {
    if (!summaries.system.tail.startsWith('v')) {
      const id = getStoredAppearance()
      summaries.system.tail = `v${APP_VERSION} · ${APPEARANCE_OPTIONS.find(o => o.id === id)?.label ?? id}`
    }
    summaries.system.state = 'ok'
  }
  return { summaries, refresh, refreshAppearanceLocal }
}
