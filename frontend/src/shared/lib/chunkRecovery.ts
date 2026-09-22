import { toast } from 'vue-sonner'

const RECOVERY_KEY = 'loci.chunk-recovery.v1'
const RETRY_WINDOW = 60_000
let recovering = false

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || '')
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Loading chunk [\w-]+ failed/i.test(message)
}

export function chunkAssetUrl(error: unknown, origin: string): string | null {
  const message = error instanceof Error ? error.message : String(error || '')
  const match = message.match(/(?:https?:\/\/[^\s"'<>]+|\/assets\/[^\s"'<>]+)\.(?:js|css)(?:\?[^\s"'<>]*)?/i)
  if (!match) return null
  try {
    const url = new URL(match[0], origin)
    return url.origin === origin && url.pathname.startsWith('/assets/') ? url.href : null
  } catch { return null }
}

export function failedChunkAssets(entries: ReadonlyArray<{ name: string; responseStatus?: number }>, origin: string): string[] {
  return [...new Set(entries.filter(entry => (entry.responseStatus ?? 0) >= 400)
    .map(entry => chunkAssetUrl(entry.name, origin)).filter((url): url is string => url !== null))]
}

async function refreshFailedChunks(error?: unknown): Promise<void> {
  const urls = new Set(failedChunkAssets(performance.getEntriesByType('resource') as PerformanceResourceTiming[], location.origin))
  const direct = chunkAssetUrl(error, location.origin)
  if (direct) urls.add(direct)
  // A nested import can fail while the thrown error names only its parent.
  // Replace cached HTTP errors before creating a fresh document/module map.
  await Promise.allSettled([...urls].map(url => fetch(url, {
    cache: 'reload', credentials: 'same-origin', signal: AbortSignal.timeout(5000),
  })))
}

export function canRetryChunk(stored: string | null, now: number): boolean {
  if (!stored) return true
  try {
    const at = Number(JSON.parse(stored).at)
    return !Number.isFinite(at) || now - at >= RETRY_WINDOW || at > now
  } catch { return true }
}

function showRetry(target = location.href): void {
  toast.error('页面资源加载失败', {
    id: 'loci-chunk-retry', duration: Infinity,
    description: navigator.onLine ? '重新载入后重试；未保存的内容会丢失。' : '网络已断开，请恢复连接后重试。',
    action: { label: '重新载入', onClick: async () => {
      if (window.confirm('重新载入会丢失当前未保存的修改，继续吗？')) {
        await refreshFailedChunks()
        location.assign(target)
      }
    } },
  })
}

/** Called only after router leave guards have accepted the destination. */
export function recoverLazyRoute(error: unknown, path: string): boolean {
  if (!isChunkLoadError(error)) return false
  const target = new URL(path, location.origin)
  if (target.origin !== location.origin) return false
  if (recovering) return true
  let retry = false
  try {
    retry = navigator.onLine && canRetryChunk(sessionStorage.getItem(RECOVERY_KEY), Date.now())
    if (retry) sessionStorage.setItem(RECOVERY_KEY, JSON.stringify({ at: Date.now() }))
  } catch { retry = false /* Storage unavailable: explicit retry, never loop. */ }
  if (!retry) { showRetry(target.href); return true }
  recovering = true
  toast.loading('正在重新载入页面资源…', { id:'loci-chunk-retry', duration:Infinity })
  void (async () => {
    try {
      await refreshFailedChunks(error)
      const shell = await fetch(target.href, { cache:'no-store', credentials:'same-origin', signal:AbortSignal.timeout(5000) })
      if (!shell.ok || !shell.headers.get('content-type')?.includes('text/html')) throw new Error('Page unavailable')
      location.assign(target.href)
    } catch {
      recovering = false
      showRetry(target.href)
    }
  })()
  return true
}

export function installChunkRecovery(): void {
  window.addEventListener('unhandledrejection', event => {
    if (!isChunkLoadError(event.reason)) return
    event.preventDefault()
    if (!recovering) showRetry()
  })
}
