import { computed, onScopeDispose, reactive, ref, watch } from 'vue'

import {
  getDataLocation,
  getMarketSyncSettings,
  getWecomSettings,
  saveDataLocation,
  saveMarketSyncSettings,
  saveWecomSettings,
  testWecomSettings,
  type DataLocationInfo,
} from '@/shared/api/quant'
import type { MarketSyncSettings, WecomSettings } from '@/shared/types/quant'

import {
  DEFAULT_WECOM_SCREEN_TEMPLATE,
  normalizeWecomScreenTemplate,
  sameWecomScreenTemplate,
  type WecomScreenTemplate,
} from './wecomScreenTemplate'

export type SectionKey = 'location' | 'sync' | 'notify' | 'appearance'

export type SectionStamp =
  | { kind: 'clean' }
  | { kind: 'dirty' }
  | { kind: 'saved'; at: string }
  | { kind: 'instant' }
  | { kind: 'pending' }

export type SyncDraft = {
  enabled_intraday: boolean
  interval_minutes: number
  enabled_eod: boolean
  eod_hour: number
  eod_minute: number
  workers: number
  push_wecom_on_fail: boolean
}

const EMPTY_SYNC: SyncDraft = {
  enabled_intraday: false,
  interval_minutes: 5,
  enabled_eod: false,
  eod_hour: 16,
  eod_minute: 0,
  workers: 4,
  push_wecom_on_fail: false,
}

function stampNow(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function syncFrom(ms: MarketSyncSettings): SyncDraft {
  return {
    enabled_intraday: ms.enabled_intraday,
    interval_minutes: ms.interval_minutes,
    enabled_eod: ms.enabled_eod,
    eod_hour: ms.eod_hour,
    eod_minute: ms.eod_minute,
    workers: ms.workers,
    push_wecom_on_fail: ms.push_wecom_on_fail,
  }
}

/** 行情同步字段（不含 push_wecom_on_fail，该开关归推送联） */
function sameSyncCore(a: SyncDraft, b: SyncDraft): boolean {
  return (
    a.enabled_intraday === b.enabled_intraday &&
    a.interval_minutes === b.interval_minutes &&
    a.enabled_eod === b.enabled_eod &&
    a.eod_hour === b.eod_hour &&
    a.eod_minute === b.eod_minute &&
    a.workers === b.workers
  )
}

export function useSystemSettings() {
  const dataLoc = ref<DataLocationInfo | null>(null)
  const wecom = ref<WecomSettings>({ configured: false, url_masked: '' })
  const syncMeta = ref<Pick<MarketSyncSettings, 'intraday_job' | 'eod_job'> | null>(null)

  const locationDir = ref('')
  const sync = reactive<SyncDraft>({ ...EMPTY_SYNC })
  const wecomUrl = ref('')
  const wecomClearPending = ref(false)
  const screenTemplate = ref<WecomScreenTemplate>(
    normalizeWecomScreenTemplate(DEFAULT_WECOM_SCREEN_TEMPLATE),
  )
  const baselineScreenTemplate = ref<WecomScreenTemplate>(
    normalizeWecomScreenTemplate(DEFAULT_WECOM_SCREEN_TEMPLATE),
  )

  const baselineDir = ref('')
  const baselineSync = reactive<SyncDraft>({ ...EMPTY_SYNC })

  const savedAt = reactive<Partial<Record<SectionKey, string>>>({})
  const sectionError = reactive<Partial<Record<SectionKey, string>>>({})
  const pendingRestart = ref(false)
  const footNotice = ref('')
  let loadVersion = 0

  onScopeDispose(() => {
    loadVersion += 1
  })

  const locationDirty = computed(
    () => locationDir.value.trim() !== '' && locationDir.value.trim() !== baselineDir.value,
  )
  const syncDirty = computed(() => !sameSyncCore(sync, baselineSync))
  const templateDirty = computed(
    () => !sameWecomScreenTemplate(screenTemplate.value, baselineScreenTemplate.value),
  )
  const notifyDirty = computed(
    () =>
      wecomUrl.value.trim() !== '' ||
      wecomClearPending.value ||
      sync.push_wecom_on_fail !== baselineSync.push_wecom_on_fail ||
      templateDirty.value,
  )
  const dirty = computed(
    () => locationDirty.value || syncDirty.value || notifyDirty.value,
  )
  const dirtyLabels = computed(() => {
    const labels: string[] = []
    if (locationDirty.value) labels.push('数据目录')
    if (syncDirty.value) labels.push('行情同步')
    if (notifyDirty.value) labels.push('推送')
    return labels
  })

  function stampFor(key: SectionKey): SectionStamp {
    if (key === 'appearance') return { kind: 'instant' }
    if (key === 'location' && pendingRestart.value && !locationDirty.value) {
      return { kind: 'pending' }
    }
    if (key === 'location' && locationDirty.value) return { kind: 'dirty' }
    if (key === 'sync' && syncDirty.value) return { kind: 'dirty' }
    if (key === 'notify' && notifyDirty.value) return { kind: 'dirty' }
    const at = savedAt[key]
    if (at) return { kind: 'saved', at }
    return { kind: 'clean' }
  }

  const stamps = computed(() => ({
    location: stampFor('location'),
    sync: stampFor('sync'),
    notify: stampFor('notify'),
    appearance: stampFor('appearance') as SectionStamp,
  }))

  async function load(): Promise<void> {
    const version = ++loadVersion
    const [dl, ms, wc] = await Promise.all([
      getDataLocation(),
      getMarketSyncSettings(),
      getWecomSettings(),
    ])
    if (version !== loadVersion) return
    dataLoc.value = dl
    locationDir.value = dl.pending_data_dir || dl.data_dir
    baselineDir.value = dl.data_dir
    pendingRestart.value = Boolean(dl.restart_required)

    Object.assign(sync, syncFrom(ms))
    Object.assign(baselineSync, syncFrom(ms))
    syncMeta.value = { intraday_job: ms.intraday_job, eod_job: ms.eod_job }

    wecom.value = wc
    wecomUrl.value = ''
    wecomClearPending.value = false
    const tpl = normalizeWecomScreenTemplate(wc.screen_template)
    screenTemplate.value = tpl
    baselineScreenTemplate.value = normalizeWecomScreenTemplate(tpl)
    footNotice.value = ''
    sectionError.location = undefined
    sectionError.sync = undefined
    sectionError.notify = undefined
  }

  function revertAll(): void {
    locationDir.value = baselineDir.value
    Object.assign(sync, { ...baselineSync })
    wecomUrl.value = ''
    wecomClearPending.value = false
    screenTemplate.value = normalizeWecomScreenTemplate(baselineScreenTemplate.value)
    footNotice.value = ''
    sectionError.location = undefined
    sectionError.sync = undefined
    sectionError.notify = undefined
  }

  function applyRecommendedSync(): void {
    sync.enabled_intraday = true
    sync.interval_minutes = 5
    sync.enabled_eod = true
    sync.eod_hour = 16
    sync.eod_minute = 0
    footNotice.value = '已填入推荐同步，请保存全部'
  }

  function markClearWecom(): void {
    wecomClearPending.value = true
    wecomUrl.value = ''
  }

  watch(wecomUrl, (value) => {
    if (value.trim()) wecomClearPending.value = false
  })

  async function testWecom(): Promise<void> {
    await testWecomSettings()
  }

  async function saveAll(): Promise<{ ok: boolean; message: string }> {
    const locWas = locationDirty.value
    const syncWas = syncDirty.value
    const pushWas = sync.push_wecom_on_fail !== baselineSync.push_wecom_on_fail
    const wecomUrlWas = wecomUrl.value.trim() !== '' || wecomClearPending.value
    const tplWas = templateDirty.value
    const wecomWas = wecomUrlWas || tplWas
    if (!locWas && !syncWas && !pushWas && !wecomWas) {
      return { ok: true, message: '无未保存改动' }
    }

    footNotice.value = ''
    sectionError.location = undefined
    sectionError.sync = undefined
    sectionError.notify = undefined

    let saved = 0
    let failed = 0
    const failBits: string[] = []
    const now = stampNow()

    if (locWas) {
      try {
        const result = await saveDataLocation({
          data_dir: locationDir.value.trim(),
          setup_done: true,
        })
        dataLoc.value = result
        locationDir.value = result.pending_data_dir || result.data_dir
        baselineDir.value = result.data_dir
        pendingRestart.value = Boolean(result.restart_required)
        savedAt.location = now
        saved += 1
        sessionStorage.removeItem('loci.bootstrap.skip')
        if (result.needed_bootstrap && !result.restart_required) {
          window.dispatchEvent(new CustomEvent('loci:setup-complete', { detail: result }))
        }
      } catch (caught: unknown) {
        failed += 1
        sectionError.location = caught instanceof Error ? caught.message : '保存失败'
        failBits.push(`数据目录：${sectionError.location}`)
      }
    }

    if (syncWas || pushWas) {
      try {
        const result = await saveMarketSyncSettings({ ...sync })
        Object.assign(sync, syncFrom(result))
        Object.assign(baselineSync, syncFrom(result))
        syncMeta.value = { intraday_job: result.intraday_job, eod_job: result.eod_job }
        if (syncWas) {
          savedAt.sync = now
          saved += 1
        }
        if (pushWas) {
          savedAt.notify = now
          if (!wecomWas) saved += 1
        }
      } catch (caught: unknown) {
        failed += 1
        const msg = caught instanceof Error ? caught.message : '保存失败'
        if (syncWas) sectionError.sync = msg
        if (pushWas) sectionError.notify = msg
        failBits.push(`行情同步：${msg}`)
      }
    }

    if (wecomWas) {
      try {
        const payload: {
          url?: string
          screen_template?: WecomScreenTemplate
        } = {}
        if (wecomUrlWas) {
          payload.url = wecomClearPending.value ? '' : wecomUrl.value.trim()
        }
        if (tplWas) {
          payload.screen_template = normalizeWecomScreenTemplate(screenTemplate.value)
        }
        const savedWecom = await saveWecomSettings(payload)
        wecom.value = savedWecom
        wecomUrl.value = ''
        wecomClearPending.value = false
        const tpl = normalizeWecomScreenTemplate(savedWecom.screen_template)
        screenTemplate.value = tpl
        baselineScreenTemplate.value = normalizeWecomScreenTemplate(tpl)
        savedAt.notify = now
        saved += 1
      } catch (caught: unknown) {
        failed += 1
        sectionError.notify = caught instanceof Error ? caught.message : '保存失败'
        failBits.push(`推送：${sectionError.notify}`)
      }
    }

    if (failed === 0) {
      const message =
        pendingRestart.value && saved > 0
          ? `${saved} 联已存 · 数据目录待重启生效`
          : `${saved} 联已存`
      footNotice.value = message
      return { ok: true, message }
    }
    const message = `${saved} 联已存 · ${failed} 联失败（${failBits.join('；')}）`
    footNotice.value = message
    return { ok: false, message }
  }

  return {
    dataLoc,
    wecom,
    syncMeta,
    locationDir,
    sync,
    wecomUrl,
    wecomClearPending,
    screenTemplate,
    pendingRestart,
    footNotice,
    sectionError,
    locationDirty,
    syncDirty,
    notifyDirty,
    dirty,
    dirtyLabels,
    stamps,
    load,
    revertAll,
    applyRecommendedSync,
    markClearWecom,
    testWecom,
    saveAll,
  }
}
