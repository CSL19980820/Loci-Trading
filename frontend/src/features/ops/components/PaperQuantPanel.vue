<script setup lang="ts">
/**
 * 工坊「纸面量化」台的编排壳（/quant?tab=paper）。
 *
 * 四张卡里只有「纸面舱」与「风格记忆」共读同一份 paper-cabin 响应，所以只有
 * 这两张吃同一个 usePaperCabin 实例；通知策略与价格提醒各走自己的接口。
 * 纵向节奏归壳管，卡自己不定纸张间距。
 */
import { onMounted } from 'vue'

import PageBusy from '@/shared/components/ui/PageBusy.vue'

import PaperAlertRulesCard from './PaperAlertRulesCard.vue'
import PaperCabinCard from './PaperCabinCard.vue'
import PaperNotifyCard from './PaperNotifyCard.vue'
import PaperRoleReviewPanel from './PaperRoleReviewPanel.vue'
import PaperStyleMemoryCard from './PaperStyleMemoryCard.vue'
import { usePaperCabin } from '../composables/usePaperCabin'

const cabin = usePaperCabin()
const { cabinBusy, leaderRoles, positions, loadCabin } = cabin

onMounted(() => {
  void loadCabin()
})
</script>

<template>
  <div class="relative flex min-h-0 min-w-0 flex-col gap-2" aria-label="纸面量化工作台">
    <PageBusy overlay :busy="cabinBusy" label="加载纸面舱…" />
    <PaperNotifyCard class="shrink-0" />
    <PaperCabinCard class="shrink-0" :cabin="cabin" />
    <PaperRoleReviewPanel :role-data="leaderRoles" :positions="positions" />
    <PaperStyleMemoryCard class="shrink-0" :cabin="cabin" />
    <PaperAlertRulesCard class="shrink-0" />
  </div>
</template>

<style scoped>
.relative :deep(.settings-panel) {
  height: auto;
  flex: 0 0 auto;
}
</style>
