<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>交割单</h1>
      <span class="chip">{{ store.trades.length }}</span>
      <span class="muted mono">买 {{ buyCount }} · 卖 {{ sellCount }} · {{ signedMoney(sellPnl) }}</span>
    </div>
    <button class="primary-button" type="button" @click="tradeDialogOpen = true">记成交</button>
  </header>

  <article class="panel">
    <div class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>日期</th>
            <th>动作</th>
            <th>标的</th>
            <th class="r">数量</th>
            <th class="r">价</th>
            <th class="r">额</th>
            <th class="r">余仓</th>
            <th class="r">成本</th>
            <th class="r">已实现</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="t in store.trades"
            :key="t.id"
            class="click-row"
            @click="goArchive(t.code)"
          >
            <td class="mono">{{ t.date }}</td>
            <td><span class="action-chip" :class="`action-${t.action.toLowerCase()}`">{{ actionLabel(t.action) }}</span></td>
            <td>
              <RouterLink :to="`/archive/${t.code}`" class="stock-link" @click.stop>
                {{ t.name }} <span class="code">{{ t.code }}</span>
              </RouterLink>
            </td>
            <td class="r mono">{{ t.shares.toLocaleString('zh-CN') }}</td>
            <td class="r mono">{{ t.price.toFixed(3) }}</td>
            <td class="r mono">{{ money(t.amount) }}</td>
            <td class="r mono">{{ t.shares_after.toLocaleString('zh-CN') }}</td>
            <td class="r mono">{{ t.cost_after ? t.cost_after.toFixed(3) : '—' }}</td>
            <td class="r mono" :class="toneClass(t.realized_pnl)">{{ signedMoney(t.realized_pnl) }}</td>
            <td class="clip">{{ t.reason || '—' }}</td>
          </tr>
          <tr v-if="!store.trades.length">
            <td colspan="10" class="empty">无成交</td>
          </tr>
        </tbody>
      </table>
    </div>
  </article>

  <TradeDialog v-model="tradeDialogOpen" />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import TradeDialog from '@/components/TradeDialog.vue'
import { actionLabel, money, signedMoney, toneClass } from '@/lib/format'
import { usePalaceStore } from '@/stores/palace'

const store = usePalaceStore()
const router = useRouter()
const tradeDialogOpen = ref(false)

const buyCount = computed(() => store.trades.filter((item) => item.action === 'BUY' || item.action === 'OPENING').length)
const sellCount = computed(() => store.trades.filter((item) => item.action === 'SELL').length)
const sellPnl = computed(() =>
  store.trades.filter((item) => item.action === 'SELL').reduce((sum, item) => sum + item.realized_pnl, 0),
)

function goArchive(code: string): void {
  void router.push(`/archive/${code}`)
}
</script>