<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  getDataLocation,
  getMarketBootstrap,
  startMarketBootstrap,
  type MarketBootstrapStatus,
} from '@/shared/api/quant'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'

const SKIP_KEY = 'loci.bootstrap.skip'
const SETUP_EVENT = 'loci:setup-complete'

const { setSyncing } = useMarketSyncGate()

const visible = ref(false)
const starting = ref(false)
const status = ref<MarketBootstrapStatus['status']>('idle')
const percent = ref(0)
const message = ref('')
const detail = ref('')
const error = ref('')
const needed = ref(false)
const backfillKind = ref<'empty' | 'catchup' | 'none' | string>('empty')
const lagTradingDays = ref(0)
const dataDirLabel = ref('data/market.db')

const isCatchup = computed(() => backfillKind.value === 'catchup')
const dialogTitle = computed(() => (isCatchup.value ? '补齐行情' : '初始化历史行情'))
const running = computed(() => status.value === 'running')
const progressStatus = computed(() => {
  if (status.value === 'done') return 'success'
  if (status.value === 'error') return 'exception'
  return undefined
})
const catchupLagHint = computed(() => {
  if (!isCatchup.value || lagTradingDays.value <= 0) return ''
  return `库内最新落后 ${lagTradingDays.value} 个交易日`
})

let timer: number | undefined

function resolveKind(snap: MarketBootstrapStatus): string {
  return snap.backfill_kind || snap.session?.backfill_kind || 'empty'
}

function syncGateMessage(snap: MarketBootstrapStatus): string {
  if (snap.message) return snap.message
  if (resolveKind(snap) === 'catchup') {
    const lag = snap.session?.lag_trading_days ?? lagTradingDays.value
    if (lag > 0) return `补齐行情（落后 ${lag} 个交易日）`
    return '补齐行情'
  }
  return '初始化历史行情'
}

function apply(snap: MarketBootstrapStatus): void {
  status.value = snap.status
  percent.value = Number(snap.percent || 0)
  message.value = snap.message || ''
  needed.value = Boolean(snap.needed)
  backfillKind.value = resolveKind(snap)
  lagTradingDays.value = snap.session?.lag_trading_days ?? 0
  const parts = [
    snap.total ? `${snap.done}/${snap.total}` : '',
    snap.code ? `当前 ${snap.code}` : '',
    isCatchup.value && lagTradingDays.value > 0
      ? `落后 ${lagTradingDays.value} 个交易日`
      : '',
  ].filter(Boolean)
  detail.value = parts.join(' · ')
  if (snap.status === 'error') error.value = snap.message || '同步失败'

  if (snap.status === 'running') {
    setSyncing(true, syncGateMessage(snap), percent.value)
  } else {
    setSyncing(false)
  }
}

async function poll(): Promise<void> {
  try {
    const snap = await getMarketBootstrap()
    apply(snap)
    if (snap.status === 'running') {
      timer = window.setTimeout(() => {
        void poll()
      }, 1000)
      return
    }
    if (snap.status === 'done') {
      percent.value = 100
    }
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '无法读取同步进度'
    status.value = 'error'
    setSyncing(false)
  }
}

async function maybeAutoStart(snap: MarketBootstrapStatus): Promise<void> {
  if (!snap.needed || snap.status === 'done') return
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
  try {
    const snap = await getMarketBootstrap()
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
    setSyncing(false)
  }
}

async function afterSetup(detailEvent?: CustomEvent): Promise<void> {
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
  starting.value = true
  error.value = ''
  try {
    const snap = await startMarketBootstrap({ with_factors: false })
    apply(snap)
    void poll()
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '启动失败'
    status.value = 'error'
    setSyncing(false)
  } finally {
    starting.value = false
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
  if (!open && timer) {
    window.clearTimeout(timer)
    timer = undefined
  }
})

onMounted(() => {
  window.addEventListener(SETUP_EVENT, onSetupComplete)
  void (async () => {
    try {
      const loc = await getDataLocation()
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
  window.removeEventListener(SETUP_EVENT, onSetupComplete)
  if (timer) window.clearTimeout(timer)
  setSyncing(false)
})
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="440px"
    :close-on-click-modal="!running"
    :close-on-press-escape="!running"
    :show-close="!running"
    destroy-on-close
  >
    <template v-if="!running && status !== 'done'">
      <template v-if="isCatchup">
        <p class="lead">
          {{ catchupLagHint || '库内最新行情落后' }}，正在后台补数。
        </p>
        <p class="hint">补齐期间请保持窗口打开；关闭可能中断同步。</p>
      </template>
      <template v-else>
        <p class="lead">本机还没有历史日 K，选股 / 回测会不可用。</p>
        <p class="hint">
          全市场首次回填大约 10–40 分钟，数据写在
          <code>{{ dataDirLabel }}</code>，可中断后续跑。
        </p>
      </template>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="mb"
      />
    </template>

    <template v-else>
      <p class="lead">
        {{
          message ||
          (isCatchup
            ? catchupLagHint
              ? `${catchupLagHint}，正在后台补数`
              : '库内最新落后交易日，正在后台补数'
            : '准备中…')
        }}
      </p>
      <el-progress
        :percentage="percent"
        :status="progressStatus"
        :stroke-width="14"
        striped
        striped-flow
      />
      <p v-if="detail" class="hint mono">{{ detail }}</p>
    </template>

    <template #footer>
      <template v-if="!running && status !== 'done'">
        <el-button v-if="!isCatchup" @click="dismiss">稍后再说</el-button>
        <el-button type="primary" :loading="starting" @click="start">
          {{ isCatchup ? '重新补齐' : '开始初始化' }}
        </el-button>
      </template>
      <template v-else-if="status === 'done' || status === 'error'">
        <el-button type="primary" @click="close">完成</el-button>
      </template>
      <template v-else>
        <span class="hint">同步中，请保持窗口打开…</span>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.lead {
  margin: 0 0 0.75rem;
  line-height: 1.5;
}
.hint {
  margin: 0.75rem 0 0;
  color: var(--el-text-color-secondary);
  font-size: 0.85rem;
  line-height: 1.45;
}
.mono {
  font-variant-numeric: tabular-nums;
}
.mb {
  margin-bottom: 0.75rem;
}
code {
  font-size: 0.85em;
}
</style>
