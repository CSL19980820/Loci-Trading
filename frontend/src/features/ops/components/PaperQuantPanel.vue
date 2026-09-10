<script setup lang="ts">
/**
 * 工坊「纸面量化」台的编排壳（/quant?tab=paper）。
 *
 * 原来是一个 633 行的 script setup 加四张卡的模板。四张卡里只有「纸面舱」与
 * 「风格记忆」共读同一份 paper-cabin 响应，所以只有这两张吃同一个 usePaperCabin
 * 实例；通知策略与价格提醒各走自己的接口、自带 composable，面板不替它们转发
 * 数据。卡上的 class="block" 由这里给：纵向节奏归壳管，卡自己不该定纸张间距。
 */
import { onMounted } from 'vue'

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
  <div class="paper-quant" v-loading="cabinBusy">
    <PaperNotifyCard class="block" />
    <PaperCabinCard class="block" :cabin="cabin" />
    <PaperRoleReviewPanel :role-data="leaderRoles" :positions="positions" />
    <PaperStyleMemoryCard class="block" :cabin="cabin" />
    <PaperAlertRulesCard class="block" />
  </div>
</template>

<style scoped>
.paper-quant {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
}
.block {
  flex: 0 0 auto;
}
</style>
