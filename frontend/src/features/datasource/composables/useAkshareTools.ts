/** AkShare 接口：本机目录浏览 + 单接口试跑 + 一键全测 + 版本检查。 */
import { computed, onScopeDispose, ref } from 'vue'

import {
  getAkshareCatalog,
  getAkshareVersion,
  probeAkshareCatalog,
  probeAkshareCatalogBatch,
} from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  AkshareBatchProbeItem,
  AkshareBatchProbeResult,
  AkshareCatalog,
  AkshareCatalogProbeResult,
  AkshareVersionInfo,
} from '@/shared/types/quant'

const LIVE_PAGE = 5

export function useAkshareTools() {
  const catalog = ref<AkshareCatalog | null>(null)
  const versionInfo = ref<AkshareVersionInfo | null>(null)
  const loading = ref(false)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const probeResult = ref<AkshareCatalogProbeResult | null>(null)
  const batchOpen = ref(false)
  const batchSummary = ref<AkshareBatchProbeResult | null>(null)
  const batchResults = ref<AkshareBatchProbeItem[]>([])
  const batchProgress = ref({ done: 0, total: 0, ok: 0, failed: 0, skipped: 0 })
  let loadVersion = 0
  let batchToken = 0
  let lifecycleToken = 0

  onScopeDispose(() => {
    lifecycleToken += 1
    loadVersion += 1
    batchToken += 1
  })

  const stats = computed(() => ({
    total: catalog.value?.capabilities.length ?? 0,
    healthOk: catalog.value?.capabilities.filter((item) => item.health_ok === true).length ?? 0,
    healthFail: catalog.value?.capabilities.filter((item) => item.health_ok === false && !String(item.health_error || '').startsWith('缺少必填')).length ?? 0,
  }))

  async function load(): Promise<void> {
    const scope = lifecycleToken
    const version = ++loadVersion
    loading.value = true
    try {
      const result = await getAkshareCatalog()
      if (scope !== lifecycleToken || version !== loadVersion) return
      catalog.value = result
      error.value = ''
    } catch (caught: unknown) {
      if (scope !== lifecycleToken || version !== loadVersion) return
      error.value = toErrorMessage(caught, 'AkShare 接口目录加载失败')
    } finally {
      if (scope === lifecycleToken && version === loadVersion) loading.value = false
    }
  }

  async function checkVersion(): Promise<void> {
    const scope = lifecycleToken
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      const info = await getAkshareVersion(true)
      if (scope !== lifecycleToken) return
      versionInfo.value = info
      if (info.error) {
        notice.value = `本机 ${info.installed || '未安装'}；查 PyPI 失败：${info.error}`
      } else if (info.update_available) {
        notice.value = `本机 ${info.installed}，PyPI 最新 ${info.latest}，可升级`
      } else {
        notice.value = `本机 ${info.installed || '未安装'}，已是最新${info.latest ? `（${info.latest}）` : ''}`
      }
    } catch (caught: unknown) {
      if (scope !== lifecycleToken) return
      error.value = toErrorMessage(caught, '版本检查失败')
    } finally {
      if (scope === lifecycleToken) busy.value = false
    }
  }

  function absorbHealth(page: AkshareBatchProbeResult): void {
    const current = catalog.value
    if (!current) return
    const byName = new Map(page.results.map((item) => [item.name, item]))
    catalog.value = {
      ...current,
      capabilities: current.capabilities.map((item) => {
        const hit = byName.get(item.name)
        if (!hit) return item
        return {
          ...item,
          health_ok: hit.skipped ? null : hit.ok,
          health_error: hit.error ?? null,
          health_elapsed_ms: hit.elapsed_ms ?? null,
        }
      }),
    }
  }

  /** 打开进度面板并分页续跑；可随时停止。 */
  async function probeAll(names?: string[]): Promise<void> {
    const scope = lifecycleToken
    const token = ++batchToken
    batchOpen.value = true
    busy.value = true
    error.value = ''
    notice.value = ''
    batchSummary.value = null
    batchResults.value = []
    batchProgress.value = { done: 0, total: 0, ok: 0, failed: 0, skipped: 0 }
    let offset = 0
    let ok = 0
    let failed = 0
    let skipped = 0
    let total = 0
    try {
      while (true) {
        if (scope !== lifecycleToken || token !== batchToken) return
        const page = await probeAkshareCatalogBatch({
          names,
          offset,
          limit: Math.min(LIVE_PAGE, catalog.value?.batch_probe_max ?? LIVE_PAGE),
        })
        if (scope !== lifecycleToken || token !== batchToken) return
        absorbHealth(page)
        batchSummary.value = page
        batchResults.value = [...batchResults.value, ...page.results]
        ok += page.ok
        failed += page.failed
        skipped += page.skipped
        total = page.total_targets
        batchProgress.value = {
          done: Math.min(page.next_offset ?? page.total_targets, page.total_targets),
          total: page.total_targets,
          ok,
          failed,
          skipped,
        }
        if (page.done || page.next_offset == null) break
        offset = page.next_offset
      }
      notice.value = `全测完成：通 ${ok} · 败 ${failed} · 跳过 ${skipped}（共 ${total}）`
    } catch (caught: unknown) {
      if (scope !== lifecycleToken || token !== batchToken) return
      error.value = toErrorMessage(caught, '一键全测失败')
    } finally {
      if (scope === lifecycleToken && token === batchToken) busy.value = false
    }
  }

  function stopBatch(): void {
    batchToken += 1
    busy.value = false
    if (batchProgress.value.total) {
      notice.value = `已停止全测（${batchProgress.value.done}/${batchProgress.value.total}）`
    }
  }

  async function probe(payload: { name: string; params: Record<string, unknown> }): Promise<void> {
    const scope = lifecycleToken
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await probeAkshareCatalog(payload.name, payload.params)
      if (scope !== lifecycleToken) return
      probeResult.value = result
      notice.value = result.error ? `${payload.name} 试跑失败` : `${payload.name} 试跑完成`
      if (catalog.value) {
        catalog.value = {
          ...catalog.value,
          capabilities: catalog.value.capabilities.map((item) =>
            item.name === payload.name
              ? {
                  ...item,
                  health_ok: !result.error,
                  health_error: result.error ?? null,
                  health_elapsed_ms: result.elapsed_ms ?? null,
                }
              : item,
          ),
        }
      }
    } catch (caught: unknown) {
      if (scope !== lifecycleToken) return
      error.value = toErrorMessage(caught, '试跑失败')
    } finally {
      if (scope === lifecycleToken) busy.value = false
    }
  }

  return {
    catalog,
    versionInfo,
    loading,
    busy,
    error,
    notice,
    probeResult,
    batchOpen,
    batchSummary,
    batchResults,
    batchProgress,
    stats,
    load,
    checkVersion,
    probeAll,
    stopBatch,
    probe,
  }
}
