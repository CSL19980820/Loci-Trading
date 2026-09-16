<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
const route = useRoute()
const id = computed(() => String(route.params.id || ''))
const GuardianStudio = defineAsyncComponent(() => import('./components/GuardianStudio.vue'))
const StockAgentStudio = defineAsyncComponent(() => import('./components/StockAgentStudio.vue'))
</script>
<template>
  <main class="agent-detail-page">
    <RouterLink class="back-link" to="/agents"><el-icon><ArrowLeft /></el-icon>全部智能体</RouterLink>
    <GuardianStudio v-if="id === 'guardian'" />
    <StockAgentStudio v-else :key="id" :id="id" />
  </main>
</template>
<style scoped>
.agent-detail-page { width:100%; max-width:1480px; margin:0 auto; padding:var(--gap-4); min-width:0; }
.back-link { display:inline-flex; gap:8px; align-items:center; color:var(--muted); text-decoration:none; font-size:13px; margin-bottom:24px; }
.back-link:hover { color:var(--seal-ink); }
@media(max-width:640px) { .agent-detail-page { padding:12px; } }
</style>
