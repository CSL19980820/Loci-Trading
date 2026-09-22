<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ArrowLeft } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { confirmAction } from '@/shared/lib/confirm'
import GuardianTab from '@/features/ops/components/GuardianTab.vue'
const workspace = ref<InstanceType<typeof GuardianTab> | null>(null)
onMounted(() => { void workspace.value?.load() })
onBeforeRouteLeave(async () => {
  if (!workspace.value?.isDirty()) return true
  return confirmAction({ message: '离开后将丢失未保存的交易员设置。', title: '放弃修改', confirmText: '离开', cancelText: '继续编辑' })
})
</script>
<template>
  <section class="guardian-studio">
    <GuardianTab ref="workspace">
      <template #leading>
        <Button access="read" variant="ghost" size="icon-sm" as-child>
          <RouterLink to="/agents" aria-label="返回智能体"><ArrowLeft aria-hidden="true" /></RouterLink>
        </Button>
      </template>
    </GuardianTab>
  </section>
</template>
<style scoped>
.guardian-studio { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
@media(max-width:767px) {
  .guardian-studio { flex:1 1 0%; min-height:0; height:100%; gap:0; overflow:hidden; }
}
@media (min-width: 1024px) and (min-height: 600px) {
  .guardian-studio { flex: 1 1 0%; min-height: 0; gap: 6px; }
  .guardian-studio :deep(.guardian-workspace) { flex: 1 1 0%; min-height: 0; }
  .guardian-studio :deep(.guardian-workspace > :not(.guardian-content-area)) { flex-shrink: 0; }
  .guardian-studio :deep(.guardian-content-area) { flex: 1 1 0%; min-height: 0; overflow: hidden; }
  .guardian-studio :deep(.guardian-content-area > :not(.review-panel):not(.research-workspace):not(.consult-panel)) { flex: 1 1 0%; min-height: 0; overflow: hidden; }
}
</style>
