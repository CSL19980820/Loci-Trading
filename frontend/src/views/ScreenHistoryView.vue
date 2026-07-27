<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>选股记录</h1>
      <span v-if="history" class="muted mono">
        {{ history.strategy }} · {{ history.total }} 条
      </span>
    </div>
    <div class="toolbar-actions">
      <button
        class="quiet-button"
        type="button"
        :disabled="syncBusy"
        @click="loadToday(true)"
        title="强制同步今日行情后重新选股"
      >
        {{ syncBusy ? '同步中…' : '今日实时选股' }}
      </button>
      <button class="quiet-button" type="button" :disabled="busy" @click="load">刷新</button>
    </div>
  </header>

  <p v-if="error" class="error-banner" role="alert"><span>{{ error }}</span></p>
  <p v-if="syncNote" class="toast" role="status">{{ syncNote }}</p>

  <!-- 战法选择 + 日期过滤 -->
  <section class="panel mb">
    <div class="filter-bar">
      <label class="inline-field">
        战法
        <select v-model="selectedStrategy" @change="load">
          <option value="">选择战法…</option>
          <option v-for="s in strategies" :key="s.slug" :value="s.slug">
            {{ s.name }} ({{ s.slug }})
          </option>
        </select>
      </label>
      <label class="inline-field">
        起始
        <input v-model="startDate" type="date" @change="load" />
      </label>
      <label class="inline-field">
        截止
        <input v-model="endDate" type="date" @change="load" />
      </label>
    </div>
  </section>

  <!-- 今日实时结果（若刚刚触发） -->
  <section v-if="todayResult" class="panel mb">
    <div class="panel-bar">
      <h2>
        今日实时结果
        <span class="chip">{{ todayResult.picks.length }} 只</span>
        <span class="chip muted-chip mono">{{ todayResult.trade_date }}</span>
      </h2>
      <span class="muted mono">{{ todayResult.entry_timing === 'open' ? '当日开盘入场' : '次日开盘入场' }}</span>
    </div>
    <p v-if="todayResult.synced" class="form-hint">
      ✓ {{ todayResult.sync_note }}
    </p>
    <div v-if="todayResult.picks.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>代码</th>
            <th class="r">开</th>
            <th class="r">收</th>
            <th v-for="key in todayFactorKeys" :key="key" class="r">{{ key }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pick in todayResult.picks" :key="pick.code">
            <td>
              <RouterLink :to="`/archive/${pick.code}`" class="stock-link">{{ pick.code }}</RouterLink>
            </td>
            <td class="r mono">{{ fmtNum(pick.open) }}</td>
            <td class="r mono">{{ fmtNum(pick.close) }}</td>
            <td v-for="key in todayFactorKeys" :key="key" class="r mono">{{ fmtNum(pick.factors[key]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty pad">当日无标的满足条件</p>
  </section>

  <!-- 历史记录（按日期分组） -->
  <template v-if="history && history.dates.length">
    <section
      v-for="date in history.dates"
      :key="date"
      class="panel mb"
    >
      <div class="panel-bar">
        <h2>
          {{ date }}
          <span class="chip">{{ history.by_date[date].length }} 只</span>
        </h2>
      </div>
      <ul class="rows">
        <li v-for="item in history.by_date[date]" :key="item.id" class="cand">
          <span class="score" :class="scoreTone(item.score)">{{ item.score ?? '—' }}</span>
          <div class="grow">
            <div class="row-main">
              <RouterLink :to="`/archive/${item.code}`" class="stock-link">
                <strong>{{ item.name }}</strong>
                <span class="code">{{ item.code }}</span>
              </RouterLink>
              <span class="tag">{{ item.decision }}</span>
              <span v-if="item.timing" class="dim">{{ item.timing }}</span>
              <span v-if="item.source !== 'job:screen'" class="chip muted-chip" title="非量化自动选股">
                {{ item.source }}
              </span>
            </div>
            <p class="reason">{{ item.reason }}</p>
          </div>
        </li>
      </ul>
    </section>
  </template>
  <p v-else-if="!busy && selectedStrategy && history" class="empty pad">
    所选战法在该区间没有选股记录。先运行一次选股任务并开启「自动写入候选池」。
  </p>
  <p v-else-if="!selectedStrategy" class="empty pad">请先选择一个战法。</p>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { CapabilityUnavailableError, getScreenHistory, getScreenToday, getStrategies } from '@/api/quant'
import type { ScreenHistory, ScreenTodayResult, StrategyInfo } from '@/types/quant'

const strategies = ref<StrategyInfo[]>([])
const selectedStrategy = ref('')
const startDate = ref('')
const endDate = ref('')

const history = ref<ScreenHistory | null>(null)
const todayResult = ref<ScreenTodayResult | null>(null)
const syncNote = ref('')
const busy = ref(false)
const syncBusy = ref(false)
const error = ref('')

const todayFactorKeys = computed(() => {
  const keys = new Set<string>()
  for (const pick of todayResult.value?.picks ?? []) {
    for (const [key, value] of Object.entries(pick.factors)) {
      if (typeof value === 'number') keys.add(key)
    }
  }
  return [...keys]
})

function scoreTone(score: number | null): string {
  if (score === null) return 'score-neutral'
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-mid'
  return 'score-low'
}

function fmtNum(value: number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '✓' : '—'
  return Number(value).toFixed(2)
}

async function load(): Promise<void> {
  if (!selectedStrategy.value) return
  busy.value = true
  error.value = ''
  try {
    history.value = await getScreenHistory({
      strategy: selectedStrategy.value,
      start: startDate.value || undefined,
      end: endDate.value || undefined,
      limit: 500,
    })
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    busy.value = false
  }
}

async function loadToday(forceSync = false): Promise<void> {
  if (!selectedStrategy.value) {
    error.value = '请先选择一个战法'
    return
  }
  syncBusy.value = true
  syncNote.value = forceSync ? '正在同步今日行情，请稍候…' : ''
  error.value = ''
  try {
    todayResult.value = await getScreenToday({
      strategy: selectedStrategy.value,
      force_sync: forceSync,
    })
    syncNote.value = todayResult.value.sync_note
      ? `行情同步完成：${todayResult.value.sync_note}`
      : ''
  } catch (e: unknown) {
    error.value =
      e instanceof CapabilityUnavailableError
        ? e.message
        : e instanceof Error
          ? e.message
          : '请求失败'
    syncNote.value = ''
  } finally {
    syncBusy.value = false
  }
}

onMounted(async () => {
  try {
    strategies.value = await getStrategies()
  } catch {
    // 依赖未装时保持空列表
  }
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: flex-end;
  padding: 8px 0 4px;
}
.toolbar-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
