/**
 * 同批切票会话：从选股/脉冲/行情台等有序列表进入档案时携带上下文。
 * 短寿命：内存 + sessionStorage；不把整表塞进 URL。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type BatchItem = {
  code: string
  name?: string
  /** 进档瞬间涨跌幅快照（小数或百分数均可；展示侧自行格式化） */
  pct?: number | null
}

export type BatchSession = {
  id: string
  source: string
  sourcePath: string
  items: BatchItem[]
  index: number
  createdAt: string
}

export type OpenBatchInput = {
  source: string
  sourcePath: string
  items: BatchItem[]
  focusCode: string
}

const STORAGE_KEY = 'loci.batchBrowse.v1'

function normalizeCode(code: string): string {
  return String(code || '').trim()
}

function dedupeItems(items: BatchItem[]): BatchItem[] {
  const seen = new Set<string>()
  const out: BatchItem[] = []
  for (const raw of items) {
    const code = normalizeCode(raw.code)
    if (!code || seen.has(code)) continue
    seen.add(code)
    out.push({
      code,
      name: raw.name?.trim() || undefined,
      pct: raw.pct ?? null,
    })
  }
  return out
}

function readStorage(): BatchSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as BatchSession
    if (!parsed?.items?.length || !parsed.sourcePath) return null
    return parsed
  } catch {
    return null
  }
}

function writeStorage(session: BatchSession | null): void {
  try {
    if (!session) sessionStorage.removeItem(STORAGE_KEY)
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // private mode / quota — 内存仍可用
  }
}

export const useBatchBrowseStore = defineStore('batchBrowse', () => {
  const session = ref<BatchSession | null>(readStorage())
  const dockOpen = ref(true)

  const active = computed(() => Boolean(session.value && session.value.items.length >= 2))
  const items = computed(() => session.value?.items ?? [])
  const index = computed(() => session.value?.index ?? -1)
  const total = computed(() => items.value.length)
  const current = computed(() => {
    const s = session.value
    if (!s || s.index < 0 || s.index >= s.items.length) return null
    return s.items[s.index] ?? null
  })
  const positionLabel = computed(() => {
    if (!active.value || index.value < 0) return ''
    return `${index.value + 1}/${total.value}`
  })

  function persist(): void {
    writeStorage(session.value)
  }

  /** 打开同批；不足 2 只则清会话（孤立链接无切票）。 */
  function openBatch(input: OpenBatchInput): void {
    const list = dedupeItems(input.items)
    const focus = normalizeCode(input.focusCode)
    if (list.length < 2) {
      clear()
      return
    }
    let idx = list.findIndex((item) => item.code === focus)
    if (idx < 0) idx = 0
    session.value = {
      id: `batch_${Date.now().toString(36)}`,
      source: input.source.trim() || '本批',
      sourcePath: input.sourcePath || '/',
      items: list,
      index: idx,
      createdAt: new Date().toISOString(),
    }
    dockOpen.value = true
    persist()
  }

  function clear(): void {
    session.value = null
    persist()
  }

  /** 路由 code 变化时对齐下标；不在批内则退出有批模式。 */
  function syncCode(code: string): void {
    const s = session.value
    if (!s?.items.length) return
    const next = normalizeCode(code)
    if (!next) return
    const idx = s.items.findIndex((item) => item.code === next)
    if (idx < 0) {
      clear()
      return
    }
    if (s.index !== idx) {
      session.value = { ...s, index: idx }
      persist()
    }
  }

  function step(delta: number): string | null {
    const s = session.value
    if (!s || s.items.length < 2) return null
    const next = s.index + delta
    if (next < 0 || next >= s.items.length) return null
    session.value = { ...s, index: next }
    persist()
    return s.items[next]?.code ?? null
  }

  function goTo(code: string): string | null {
    const s = session.value
    if (!s) return null
    const next = normalizeCode(code)
    const idx = s.items.findIndex((item) => item.code === next)
    if (idx < 0) return null
    session.value = { ...s, index: idx }
    persist()
    return next
  }

  function setDockOpen(open: boolean): void {
    dockOpen.value = open
  }

  function toggleDock(): void {
    dockOpen.value = !dockOpen.value
  }

  return {
    session,
    dockOpen,
    active,
    items,
    index,
    total,
    current,
    positionLabel,
    openBatch,
    clear,
    syncCode,
    step,
    goTo,
    setDockOpen,
    toggleDock,
  }
})
