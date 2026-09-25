<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, ref, watch } from 'vue'
import { ChevronRight, ChartNoAxesCombined } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import type { GuardianAccount, GuardianExperience } from '@/shared/types/guardian'
import GuardianExperiencePanel from './GuardianExperiencePanel.vue'
import GuardianPositionsMobile from './GuardianPositionsMobile.vue'
import GuardianPositionDetails from './GuardianPositionDetails.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
const mobile = useMobileLayout()
const GuardianTradesPanel = defineAsyncComponent(() => import('./GuardianTradesPanel.vue'))
const GuardianPerformancePanel = defineAsyncComponent(() => import('./GuardianPerformancePanel.vue'))
const props = defineProps<{ account: GuardianAccount; experience?: GuardianExperience }>()
const positionDetailCode = ref('')
const selectedPosition = computed(() => props.account.positions.find(row => row.code === positionDetailCode.value))
const positionDetailOpen = computed({ get: () => Boolean(selectedPosition.value), set: value => { if (!value) positionDetailCode.value = '' } })
const tab = ref('positions')
const GuardianHoldingCurve = defineAsyncComponent(() => import('./GuardianHoldingCurve.vue'))
const emit = defineEmits<{ review: []; 'section-change': [value: string] }>()
watch(tab, value => emit('section-change', value), { immediate: true })
const curveCode = ref(''), accountHost = ref<HTMLElement>()
async function selectCurve(code: string): Promise<void> {
  curveCode.value = code
  tab.value = 'curve'
  await nextTick()
  const trigger = accountHost.value?.querySelector<HTMLElement>('[data-curve-tab]')
  trigger?.focus({ preventScroll: true })
  trigger?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' })
}
const money = (cents?: number) => cents == null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pnlClass = (value: number) => value > 0 ? 'gain' : value < 0 ? 'loss' : ''
const cost = (value?: number) => value == null ? '—' : value.toFixed(4)
const pnlPct = (row: { unrealized_pnl_cents: number; cost_cents: number }) => {
  if (!row.cost_cents) return ''
  const pct = row.unrealized_pnl_cents / row.cost_cents * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`
}
/** `Tabs` 的 modelValue 是 reka-ui 的 `AcceptableValue`，这里收成本页的 string 档 */
function onTabChange(value: unknown): void {
  tab.value = String(value)
}
</script>

<template>
  <section ref="accountHost" class="guardian-account" aria-label="守护现金账户">
    <Tabs :model-value="tab" class="account-tabs" @update:model-value="onTabChange">
      <div class="account-tabs__navigation">
      <TabsList class="account-tabs__list" aria-label="账户明细">
        <TabsTrigger value="positions" class="account-tab">持仓<span class="account-tab__count">{{ account.positions.length }}</span></TabsTrigger>
        <TabsTrigger value="curve" data-curve-tab class="account-tab">持仓曲线</TabsTrigger>
        <TabsTrigger value="experience" class="account-tab">经验沉淀<span v-if="experience?.items.length" class="account-tab__count">{{ experience.items.length }}</span></TabsTrigger>
        <TabsTrigger value="trades" class="account-tab">成交明细</TabsTrigger>
        <TabsTrigger value="performance" class="account-tab">个股盈亏</TabsTrigger>
      </TabsList>
      </div>
      <TabsContent value="positions" class="account-tabs__panel positions-panel">
        <GuardianPositionsMobile v-if="mobile" :account="account" @curve="selectCurve" @detail="positionDetailCode = $event" />
        <div v-else-if="account.positions.length" class="position-cards-grid" aria-label="精确持仓明细">
          <article v-for="row in account.positions" :key="row.code" class="position-card" :class="`is-${pnlClass(row.unrealized_pnl_cents) || 'flat'}`">
            <header class="position-card-head">
              <div class="position-identity">
                <h4>{{ row.name }}</h4>
                <span class="position-code">{{ row.code }}</span>
                <Button access="read" variant="ghost" size="xs" class="position-curve-link" :aria-label="`查看${row.name}持仓曲线`" @click="selectCurve(row.code)"><ChartNoAxesCombined :size="13" />走势</Button>
              </div>
              <div class="position-pnl" :class="pnlClass(row.unrealized_pnl_cents)">
                <strong>{{ (row.unrealized_pnl_cents ?? 0) > 0 ? '+' : '' }}{{ money(row.unrealized_pnl_cents) }}</strong>
                <span v-if="pnlPct(row)">{{ pnlPct(row) }}</span>
              </div>
            </header>

            <div class="position-metrics-strip">
              <div><span class="metric-dt">持仓 / 可卖</span><span class="metric-dd">{{ row.quantity.toLocaleString() }} / {{ row.available_quantity.toLocaleString() }} 股</span></div>
              <div><span class="metric-dt">含费成本</span><span class="metric-dd">{{ cost(row.average_cost) }} 元</span></div>
              <div><span class="metric-dt">参考现价</span><span class="metric-dd">{{ money(row.mark_price_cents) }} 元</span></div>
              <div><span class="metric-dt">成本总额</span><span class="metric-dd">{{ money(row.cost_cents) }} 元</span></div>
            </div>

            <div class="position-plan-preview">
              <p>{{ row.holding_plan || '等待下一轮研判' }}</p>
              <Button access="read" variant="ghost" size="sm" :aria-label="`查看${row.name}持仓详情`" @click="positionDetailCode = row.code">详情<ChevronRight /></Button>
            </div>
          </article>
        </div>
        <EmptyState v-else compact description="当前空仓" />
      </TabsContent>
      <TabsContent value="curve" class="account-tabs__panel curve-panel">
        <GuardianHoldingCurve v-model:selected-code="curveCode" :account="account" @review="emit('review')" />
      </TabsContent>
      <TabsContent value="trades" class="account-tabs__panel"><GuardianTradesPanel /></TabsContent>
      <TabsContent value="experience" class="account-tabs__panel"><GuardianExperiencePanel :experience="experience" /></TabsContent>
      <TabsContent value="performance" class="account-tabs__panel"><GuardianPerformancePanel :account="account" /></TabsContent>
    </Tabs>
    <GuardianPositionDetails v-model:open="positionDetailOpen" :position="selectedPosition" />

  </section>
</template>

<style scoped src="./GuardianAccountPanel.css"></style>
