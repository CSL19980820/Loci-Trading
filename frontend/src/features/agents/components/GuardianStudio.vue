<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import GuardianTab from '@/features/ops/components/GuardianTab.vue'
import GuardianStoragePanel from './GuardianStoragePanel.vue'
const workspace = ref<InstanceType<typeof GuardianTab> | null>(null)
onMounted(() => { void workspace.value?.load() })
onBeforeRouteLeave(async () => {
  if (!workspace.value?.isDirty()) return true
  try { await ElMessageBox.confirm('离开后将丢失未保存的交易员设置。', '放弃修改', { confirmButtonText:'离开', cancelButtonText:'继续编辑' }); return true }
  catch { return false }
})
</script>
<template><section class="guardian-studio"><GuardianTab ref="workspace" /><GuardianStoragePanel /></section></template>
<style scoped>
.guardian-studio { min-width:0; }
.guardian-studio :deep(.guardian-header) { padding-bottom:20px; }
.guardian-studio :deep(.guardian-navigation) { margin:20px 0; }
</style>
