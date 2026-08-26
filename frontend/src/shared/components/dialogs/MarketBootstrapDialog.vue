<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  getDataLocation,
  getMarketBootstrap,
  startMarketBootstrap,
  type MarketBootstrapStatus,
} from '@/shared/api/quant'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'

import MarketBootstrapStatusPanel from './MarketBootstrapStatusPanel.vue'

const SKIP_KEY = 'loci.bootstrap.skip'
const SETUP_EVENT = 'loci:setup-complete'
const OPEN_EVENT = 'loci:open-bootstrap'

const { setSyncing } = useMarketSyncGate()

const visible = ref(false)
const starting = ref(false)
const pendingFactors = ref(false)
const status = ref<MarketBootstrapStatus['status']>('idle')
const percent = ref(0)
const message = ref('')
const detail = ref('')
const error = ref('')
const needed = ref(false)
const backfillKind = ref<'empty' | 'catchup' | 'none' | string>('empty')
const lagTradingDays = ref(0)
const coverageLast = ref('')
const coverageFirst = ref('')
const backfillFrom = ref('')
const backfillTo = ref('')
const expectedLast = ref('')
const dataDirLabel = ref('data/market.db')
const reportSummary = ref('')

const isCatchup = computed(() => backfillKind.value === 'catchup')
const dialogTitle = computed(() => (isCatchup.value ? '补齐行情' : '初始化行情'))
const running = computed(() => status.value === 'running')
const isDone = computed(() => status.value === 'done')
const isError = computed(() => status.value === 'error')
const phaseLabel = computed(() => {
  if (isDone.value) return '已完成'
  if (isError.value) return '失败'
  if (running.value) return '同步中'
  return isCatchup.value ? '待补齐' : '待初始化'
})

/** 将补区间文案：单日或 from → to */
const rangeLabel = computed(() => {
  const from = backfillFrom.value
  const to = backfillTo.value || expectedLast.value
  if (!to && !from) return ''
  if (from && to && from !== to) return `${from} → ${to}`
  return from || to
})

const lagLabel = computed(() => {
  const n = lagTradingDays.value
  if (n <= 0) return ''
  if (n >= 99) return '空库'
  return `${n} 个交易日`
})

const leadText = computed(() => {
  if (isDone.value) return '行情已就绪'
  if (running.value) {
    if (message.value && !/Error|Exception/i.test(message.value)) return message.value
    if (isCatchup.value) {
      return rangeLabel.value ? `正在补齐 ${rangeLabel.value}` : '正在补齐落后交易日…'
    }
    return '正在拉取历史日线…'
  }
  if (isCatchup.value) {
    if (coverageLast.value && rangeLabel.value) {
      return `库内最新到 ${coverageLast.value}，将补齐 ${rangeLabel.value}。`
    }
    return '库内最新行情落后，需要补齐最近交易日。'
  }
  return '本机还没有历史日 K，选股与回测暂时不可用。'
})

let timer: number | undefined
let mounted = false
let pollGeneration = 0
let pollInFlight = false
let probeSeq = 0
let startSeq = 0
let externalSeq = 0

function stopPolling(): void {
  pollGeneration += 1
  pollInFlight = false
  if (timer) {
    window.clearTimeout(timer)
    timer = undefined
  }
}

function humanizeError(raw: string): string {
  const text = raw.trim()
  if (!text) return '同步失败'
  if (/calendar\.json|file_fold/i.test(text)) {
    return '行情日历文件缺失，当前安装包不完整。请重新全量打包后再试，或联系维护者补齐 akshare 资源。'
  }
  if (/证券列表全部失败|交易所列表异常/i.test(text)) {
    return '证券列表拉取失败。请检查网络后点「重新补齐」；若反复失败，到运维页手动同步证券列表。'
  }
  if (/Connection|Timeout|timed out|Max retries/i.test(text)) {
    return '网络超时，请稍后重试。'
  }
  const cleaned = text
    .replace(/^SourceError:\s*/i, '')
    .replace(/^AdapterError:\s*/i, '')
    .replace(/\s*->\s*/g, ' · ')
  if (cleaned.length > 160) return `${cleaned.slice(0, 158)}…`
  return cleaned
}

function resolveKind(snap: MarketBootstrapStatus): string {
  return snap.backfill_kind || snap.session?.backfill_kind || 'empty'
}

function syncGateMessage(snap: MarketBootstrapStatus): string {
  if (snap.message && !/Error|Exception|Traceback/i.test(snap.message)) return snap.message
  const sess = snap.session
  if (resolveKind(snap) === 'catchup') {
    const from = sess?.backfill_from
    const to = sess?.backfill_to || sess?.expected_last_date
    if (from && to && from !== to) return `补齐行情 ${from} → ${to}`
    if (to) return `补齐行情至 ${to}`
    const lag = sess?.lag_trading_days ?? lagTradingDays.value
    if (lag > 0) return `补齐行情（落后 ${lag} 个交易日）`
    return '补齐行情'
  }
  return '初始化历史行情'
}

function apply(snap: MarketBootstrapStatus): void {
  if (!mounted) return
  status.value = snap.status
  percent.value = Number(snap.percent || 0)
  message.value = snap.message || ''
  needed.value = Boolean(snap.needed)
  backfillKind.value = resolveKind(snap)
  const sess = snap.session
  lagTradingDays.value = sess?.lag_trading_days ?? 0
  coverageLast.value =
    sess?.coverage_last_date || snap.coverage?.last_date || ''
  coverageFirst.value =
    sess?.coverage_first_date || snap.coverage?.first_date || ''
  backfillFrom.value = sess?.backfill_from || ''
  backfillTo.value = sess?.backfill_to || ''
  expectedLast.value = sess?.expected_last_date || ''
  const parts = [
    snap.total ? `${snap.done}/${snap.total}` : '',
    snap.code ? `当前 ${snap.code}` : '',
  ].filter(Boolean)
  detail.value = parts.join(' · ')
  if (snap.status === 'error') error.value = humanizeError(snap.message || '同步失败')
  if (snap.status === 'done' && snap.report) {
    const r = snap.report
    reportSummary.value = [
      r.succeeded != null ? `成功 ${r.succeeded}` : '',
      r.failed != null ? `失败 ${r.failed}` : '',
      r.skipped != null ? `跳过 ${r.skipped}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
  } else if (snap.status !== 'done') {
    reportSummary.value = ''
  }

  if (snap.status === 'running') {
    setSyncing(true, syncGateMessage(snap), percent.value)
  } else {
    setSyncing(false)
  }
}

async function poll(): Promise<void> {
  if (!mounted || pollInFlight) return
  if (timer) {
    window.clearTimeout(timer)
    timer = undefined
  }
  const generation = pollGeneration
  pollInFlight = true
  try {
    const snap = await getMarketBootstrap()
    if (!mounted || generation !== pollGeneration) return
    apply(snap)
    if (snap.status === 'running') {
      timer = window.setTimeout(() => {
        timer = undefined
        void poll()
      }, 1000)
      return
    }
    if (snap.status === 'done') {
      percent.value = 100
    }
  } catch (caught: unknown) {
    if (!mounted || generation !== pollGeneration) return
    error.value = humanizeError(caught instanceof Error ? caught.message : '无法读取同步进度')
    status.value = 'error'
    setSyncing(false)
  } finally {
    if (generation === pollGeneration) pollInFlight = false
  }
}

async function maybeAutoStart(snap: MarketBootstrapStatus): Promise<void> {
  if (!mounted || !snap.needed || snap.status === 'done') return
  visible.value = true
  if (snap.status === 'running') {
    void poll()
    return
  }
  if (snap.status === 'idle') {
    await start()
  }
}

async function probe(): Promise<void> {
  if (!mounted) return
  const seq = ++probeSeq
  try {
    const snap = await getMarketBootstrap()
    if (!mounted || seq !== probeSeq) return
    apply(snap)
    const kind = resolveKind(snap)

    if (snap.status === 'running') {
      visible.value = true
      void poll()
      return
    }

    if (sessionStorage.getItem(SKIP_KEY) === '1' && kind !== 'catchup') return

    if (snap.needed && snap.status !== 'done') {
      await maybeAutoStart(snap)
    }
  } catch {
    if (mounted && seq === probeSeq) setSyncing(false)
  }
}

async function afterSetup(detailEvent?: CustomEvent): Promise<void> {
  if (!mounted) return
  const info = detailEvent?.detail as
    | { data_dir?: string; needed_bootstrap?: boolean; market_db?: string }
    | null
    | undefined
  if (info?.market_db) dataDirLabel.value = info.market_db
  else if (info?.data_dir) dataDirLabel.value = `${info.data_dir}/market.db`
  if (info?.needed_bootstrap) {
    sessionStorage.removeItem(SKIP_KEY)
  }
  await probe()
}

async function start(): Promise<void> {
  if (!mounted || starting.value) return
  const seq = ++startSeq
  starting.value = true
  error.value = ''
  reportSummary.value = ''
  try {
    const snap = await startMarketBootstrap({ with_factors: pendingFactors.value })
    if (!mounted || seq !== startSeq) return
    apply(snap)
    void poll()
  } catch (caught: unknown) {
    if (!mounted || seq !== startSeq) return
    error.value = humanizeError(caught instanceof Error ? caught.message : '启动失败')
    status.value = 'error'
    setSyncing(false)
  } finally {
    if (mounted && seq === startSeq) starting.value = false
  }
}

/** 体检页等外部入口：打开弹窗并跟随/启动补齐。 */
async function openFromExternal(ev: Event): Promise<void> {
  if (!mounted) return
  const seq = ++externalSeq
  const detailEvent = (ev as CustomEvent).detail as
    | { with_factors?: boolean; autoStart?: boolean }
    | null
    | undefined
  pendingFactors.value = Boolean(detailEvent?.with_factors)
  const autoStart = detailEvent?.autoStart !== false
  sessionStorage.removeItem(SKIP_KEY)
  visible.value = true
  error.value = ''
  try {
    const snap = await getMarketBootstrap()
    if (!mounted || seq !== externalSeq) return
    apply(snap)
    if (snap.status === 'running') {
      void poll()
      return
    }
    // 体检页再次点修复时，即使上次 done/error 也要重新跑
    if (autoStart) {
      await start()
    }
  } catch (caught: unknown) {
    if (!mounted || seq !== externalSeq) return
    error.value = humanizeError(caught instanceof Error ? caught.message : '无法打开补齐进度')
    status.value = 'error'
  }
}

function dismiss(): void {
  if (isCatchup.value) return
  sessionStorage.setItem(SKIP_KEY, '1')
  visible.value = false
}

function close(): void {
  visible.value = false
  if (status.value === 'done') {
    sessionStorage.removeItem(SKIP_KEY)
  }
}

function onSetupComplete(ev: Event): void {
  void afterSetup(ev as CustomEvent)
}

watch(visible, (open) => {
  // 关闭弹窗时若仍在跑，继续轮询以更新顶栏进度；仅在非 running 时清 timer
  if (!open && status.value !== 'running') stopPolling()
})

onMounted(() => {
  mounted = true
  window.addEventListener(SETUP_EVENT, onSetupComplete)
  window.addEventListener(OPEN_EVENT, openFromExternal)
  void (async () => {
    try {
      const loc = await getDataLocation()
      if (!mounted) return
      dataDirLabel.value = loc.market_db || `${loc.data_dir}/market.db`
      if (!loc.needs_setup) {
        await probe()
      }
    } catch {
      await probe()
    }
  })()
})

onUnmounted(() => {
  mounted = false
  probeSeq += 1
  startSeq += 1
  externalSeq += 1
  window.removeEventListener(SETUP_EVENT, onSetupComplete)
  window.removeEventListener(OPEN_EVENT, openFromExternal)
  stopPolling()
  setSyncing(false)
})
</script>

<template>
  <el-dialog
    v-model="visible"
    width="560px"
    align-center
    :close-on-click-modal="true"
    :close-on-press-escape="true"
    :show-close="true"
    destroy-on-close
    class="boot-dialog"
    :aria-label="dialogTitle"
  >
    <template #header>
      <div class="boot-head">
        <span class="boot-seal" aria-hidden="true">LC</span>
        <div class="boot-head-text">
          <p class="boot-kicker">{{ phaseLabel }}</p>
          <h2 class="boot-title">{{ dialogTitle }}</h2>
        </div>
      </div>
    </template>

    <MarketBootstrapStatusPanel
      :is-catchup="isCatchup"
      :coverage-last="coverageLast"
      :expected-last="expectedLast"
      :range-label="rangeLabel"
      :lag-label="lagLabel"
      :running="running"
      :is-done="isDone"
      :is-error="isError"
      :lead-text="leadText"
      :data-dir-label="dataDirLabel"
      :error="error"
      :percent="percent"
      :detail="detail"
      :report-summary="reportSummary"
    />

    <template #footer>
      <div class="boot-foot">
        <template v-if="!running && !isDone">
          <el-button
            v-if="!isCatchup"
            native-type="button"
            class="boot-btn boot-btn--ghost"
            @click="dismiss"
          >
            稍后再说
          </el-button>
          <el-button
            native-type="button"
            class="boot-btn boot-btn--seal"
            :disabled="starting"
            @click="start"
          >
            {{ starting ? '启动中…' : isCatchup ? (error ? '重新补齐' : '开始补齐') : '开始初始化' }}
          </el-button>
        </template>
        <template v-else-if="isDone || isError">
          <el-button
            v-if="isError"
            native-type="button"
            class="boot-btn boot-btn--ghost"
            :disabled="starting"
            @click="start"
          >
            重试
          </el-button>
          <el-button native-type="button" class="boot-btn boot-btn--seal" @click="close">
            {{ isDone ? '完成' : '关闭' }}
          </el-button>
        </template>
        <template v-else>
          <el-button native-type="button" class="boot-btn boot-btn--ghost" @click="close">
            后台继续
          </el-button>
          <p class="boot-foot-note">关闭弹窗后顶栏仍显示进度</p>
        </template>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.boot-head {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.boot-seal {
  flex-shrink: 0;
  width: 2.4rem;
  height: 2.4rem;
  display: grid;
  place-items: center;
  border: 1.5px solid var(--seal);
  border-radius: 50%;
  color: var(--seal-ink);
  background: var(--seal-soft);
  font: 700 0.72rem/1 var(--font-display);
  letter-spacing: 0.04em;
}

.boot-kicker {
  margin: 0 0 0.15rem;
  color: var(--mist);
  font: 500 0.72rem/1.2 var(--mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.boot-title {
  margin: 0;
  color: var(--ink);
  font: 650 1.15rem/1.2 var(--font-display);
  letter-spacing: 0.02em;
}

.boot-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.55rem;
  width: 100%;
}

.boot-foot-note {
  margin: 0;
  color: var(--mist);
  font-size: 0.82rem;
}

.boot-btn.el-button {
  appearance: none;
  height: auto;
  margin: 0;
  border: 1px solid transparent;
  border-radius: var(--radius);
  padding: 0.45rem 0.95rem;
  font: 550 0.88rem/1.2 var(--font);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.boot-btn.el-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.boot-btn--ghost.el-button {
  border-color: var(--rule);
  background: var(--sheet);
  color: var(--ink);
}

.boot-btn--ghost.el-button:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--seal) 35%, var(--rule));
  background: var(--panel-2, var(--paper));
}

.boot-btn--seal.el-button {
  border-color: color-mix(in srgb, var(--seal) 55%, transparent);
  background: var(--seal);
  color: #fff;
}

.boot-btn--seal.el-button:hover:not(:disabled) {
  background: var(--seal-ink);
}

</style>

<style>
/* 非 scoped：收束 Element Plus 对话框壳，贴合账本纸感 */
.boot-dialog.el-dialog {
  --el-dialog-bg-color: var(--sheet);
  --el-dialog-padding-primary: 1.15rem 1.25rem;
  border: 1px solid var(--rule);
  border-radius: calc(var(--radius) + 2px);
  box-shadow: 0 18px 48px rgba(20, 32, 51, 0.12);
  overflow: hidden;
}

.boot-dialog .el-dialog__header {
  margin: 0;
  padding: 1rem 1.25rem 0.85rem;
  border-bottom: 1px solid var(--rule);
  background: linear-gradient(180deg, var(--sheet) 0%, color-mix(in srgb, var(--paper) 55%, var(--sheet)) 100%);
}

.boot-dialog .el-dialog__headerbtn {
  top: 1rem;
  right: 1rem;
}

.boot-dialog .el-dialog__body {
  padding: 1rem 1.25rem 0.35rem;
}

.boot-dialog .el-dialog__footer {
  padding: 0.85rem 1.25rem 1.1rem;
  border-top: 1px solid var(--rule);
  background: var(--panel-2, var(--paper));
}
</style>
