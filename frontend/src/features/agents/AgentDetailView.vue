<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceLoading from '@/shared/components/ui/WorkspaceLoading.vue'
const route = useRoute()
const id = computed(() => String(route.params.id || ''))
const GuardianStudio = defineAsyncComponent({ loader: () => import('./components/GuardianStudio.vue'), loadingComponent: WorkspaceLoading, delay: 0 })
const StockAgentStudio = defineAsyncComponent({ loader: () => import('./components/StockAgentStudio.vue'), loadingComponent: WorkspaceLoading, delay: 0 })
</script>
<template>
  <div class="agent-detail-page page-fill">
    <!-- 工作室占满可用高度；各栏目自己滚动，身份与导航保持可见。 -->
    <div class="agent-detail-scroll page-scroll page-scroll--flush-top" :class="{ 'agent-detail-scroll--guardian': id === 'guardian' }">
      <GuardianStudio v-if="id === 'guardian'" />
      <StockAgentStudio v-else-if="id" :key="id" :id="id" />
    </div>
  </div>
</template>
<style scoped>
.agent-detail-page {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.agent-detail-scroll {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  overflow-x: hidden;
  overscroll-behavior: contain;
}
.agent-detail-scroll { padding-top: 8px; padding-bottom: 8px; }
@media(max-width:767px) {
  .agent-detail-scroll--guardian { overflow:hidden; padding:0; }
}
</style>
