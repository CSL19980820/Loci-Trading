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
    <!-- 页头由各工作室自己渲染（它们知道自己的名字与状态），sticky 依赖这一层滚动容器 -->
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
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
}
@media (min-width: 1024px) and (min-height: 600px) {
  .agent-detail-scroll--guardian { overflow: hidden; padding-bottom: 8px; }
}
@media(max-width:767px) {
  .agent-detail-scroll--guardian { overflow:hidden; padding:0; }
}
</style>
