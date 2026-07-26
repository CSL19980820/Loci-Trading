<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>候选池</h1>
      <span v-if="day" class="muted mono">{{ day.date }} · {{ day.selected_count }}/{{ day.total }}</span>
    </div>
  </header>

  <section class="pool-layout">
    <aside class="panel pool-aside">
      <ul v-if="store.pools.length" class="day-list">
        <li v-for="item in store.pools" :key="`${item.date}-${item.pool_id}`">
          <button
            type="button"
            class="day-item"
            :class="{ active: selectedDate === item.date && selectedPoolId === item.pool_id }"
            @click="selectPool(item.date, item.pool_id)"
          >
            <strong class="mono">{{ item.date.slice(5) }}</strong>
            <span>{{ item.selected }}/{{ item.total }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="empty pad">无池</p>
    </aside>

    <div class="pool-main">
      <div class="stat-strip mini">
        <div class="stat"><span class="stat-k">全量</span><span class="stat-v">{{ day?.total ?? 0 }}</span></div>
        <div class="stat tone-up"><span class="stat-k">精选</span><span class="stat-v">{{ day?.selected_count ?? 0 }}</span></div>
        <div class="stat tone-down"><span class="stat-k">未选</span><span class="stat-v">{{ day?.filtered_count ?? 0 }}</span></div>
      </div>

      <!-- 纪要不重复列精选股；明细在下方「精选 / 未精选」面板 -->
      <article v-if="day?.summary && summaryVisible" class="panel brief-panel">
        <div class="panel-bar">
          <h2>当日纪要</h2>
          <span v-if="day.summary.all_selected" class="chip muted-chip">全选</span>
        </div>
        <div class="brief">
          <div class="brief-top">
            <strong class="brief-title">{{ day.summary.headline }}</strong>
          </div>
          <p v-if="day.summary.note" class="brief-note brief-note-flush">{{ day.summary.note }}</p>
        </div>
      </article>

      <article class="panel">
        <div class="panel-bar"><h2>精选</h2></div>
        <ul v-if="day?.selected.length" class="rows">
          <li v-for="item in day.selected" :key="item.id" class="cand">
            <span class="score score-high">{{ item.score ?? '—' }}</span>
            <div class="grow">
              <div class="row-main">
                <strong>{{ item.name }}</strong>
                <span class="code">{{ item.code }}</span>
                <span class="tag">{{ item.decision }}</span>
                <span class="dim">{{ item.timing }}</span>
              </div>
              <p class="reason">{{ item.reason }}</p>
            </div>
          </li>
        </ul>
        <p v-else class="empty pad">—</p>
      </article>

      <article class="panel">
        <div class="panel-bar"><h2>未精选</h2></div>
        <ul v-if="day?.filtered.length" class="rows">
          <li v-for="item in day.filtered" :key="item.id" class="cand">
            <span class="score" :class="scoreTone(item.score)">{{ item.score ?? '—' }}</span>
            <div class="grow">
              <div class="row-main">
                <strong>{{ item.name }}</strong>
                <span class="code">{{ item.code }}</span>
                <span class="tag">{{ item.decision }}</span>
              </div>
              <p class="reason">{{ item.reason }}</p>
            </div>
          </li>
        </ul>
        <p v-else class="empty pad">—</p>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { usePalaceStore } from '@/stores/palace'

const store = usePalaceStore()
const selectedDate = computed(() => store.selectedPoolDate)
const selectedPoolId = computed(() => store.selectedPoolId)
const day = computed(() => store.poolDay)

/** 有结论或备注才显示纪要条，避免空面板 */
const summaryVisible = computed(() => {
  const s = day.value?.summary
  if (!s) return false
  return Boolean(s.headline || s.note)
})

async function selectPool(date: string, poolId: string): Promise<void> {
  await store.loadPoolDay(date, poolId)
}

function scoreTone(score: number | null): string {
  if (score === null) return 'score-neutral'
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-mid'
  return 'score-low'
}
</script>