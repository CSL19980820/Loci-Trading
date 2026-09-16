<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { GuardianConfig } from '@/shared/types/guardian'
import type { LlmProvider } from '@/shared/types/quant'
const open = defineModel<boolean>({ default: false })
const props = defineProps<{ config: GuardianConfig; defaultPrompt: string; providers: LlmProvider[]; busy: boolean; error: string; startOnSave: boolean }>()
const emit = defineEmits<{ save: [config: GuardianConfig] }>()
const draft = ref<GuardianConfig>({ ...props.config })
const baseline = ref('')
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
const models = computed(() => props.providers.find(p => p.name === draft.value.provider)?.models ?? [])
watch(open, value => {
  if (!value) return
  draft.value = JSON.parse(JSON.stringify(props.config))
  baseline.value = JSON.stringify(draft.value)
  if (props.startOnSave) draft.value.enabled = true
})
async function close(done: () => void) {
  if (dirty.value) {
    try { await ElMessageBox.confirm('关闭后将丢失未保存的交易员配置。', '放弃修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' }) }
    catch { return }
  }
  done()
}
defineExpose({ isDirty: () => open.value && dirty.value })
</script>
<template>
  <el-drawer v-model="open" class="guardian-settings-drawer" title="交易员设置" size="min(560px, 100vw)" :before-close="close" :close-on-click-modal="false">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-form label-position="top" @submit.prevent>
      <div class="settings-section-title"><span>01</span><h3>选择模型</h3></div>
      <el-form-item label="模型供应商"><el-select v-model="draft.provider" placeholder="选择已配置的供应商" @change="draft.model = ''"><el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.name" /></el-select></el-form-item>
      <el-form-item label="守护模型"><el-select v-model="draft.model" filterable placeholder="选择模型"><el-option v-for="m in models" :key="m" :label="m" :value="m" /></el-select></el-form-item>
      <div class="settings-section-title"><span>02</span><h3>管理偏好</h3><el-button link @click="draft.prompt = defaultPrompt">恢复内置提示词</el-button></div>
      <el-form-item label="给守护的提示词"><el-input v-model="draft.prompt" type="textarea" :rows="12" :maxlength="16000" show-word-limit aria-label="交易员提示词" /></el-form-item>
      <div class="settings-section-title"><span>03</span><h3>运行与通知</h3></div>
      <el-form-item label="启动交易员"><el-switch v-model="draft.enabled" active-text="交易时段每 5 分钟运行" aria-label="启动交易员" /></el-form-item>
      <el-form-item label="合并推送"><el-switch v-model="draft.notify" active-text="使用已配置的通知通道" /></el-form-item>
    </el-form>
    <template #footer><div class="settings-footer"><span>{{ dirty ? '有未保存的修改' : '配置已同步' }}</span><el-button :disabled="busy" @click="open = false">取消</el-button><el-button type="primary" :loading="busy" @click="emit('save', draft)">保存配置</el-button></div></template>
  </el-drawer>
</template>
<style scoped>
.settings-section-title { display: flex; align-items: center; gap: var(--gap-2); margin: var(--gap-4) 0 var(--gap-3); }
.settings-section-title > span { font: var(--fs-aux) var(--mono); color: var(--mist); }
.settings-section-title h3 { margin: 0; font-size: var(--fs-body); font-weight: 600; }
.settings-section-title .el-button { margin-left: auto; }
.settings-footer { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gap-2); }
.settings-footer > span { margin-right: auto; color: var(--muted); font-size: var(--fs-aux); }
.settings-section-title { padding-bottom: var(--gap-2); border-bottom: 1px solid var(--rule); }
.settings-section-title > span { color: var(--seal-ink); background: var(--seal-soft); padding: var(--gap-1) var(--gap-2); border-radius: var(--radius-sm); }
.guardian-settings-drawer :deep(.el-drawer__body) { overscroll-behavior: contain; }
.guardian-settings-drawer :deep(.el-drawer__footer) { border-top: 1px solid var(--rule); background: var(--surface-sunken); }
@media(max-width:480px) { .settings-footer > span { width:100%; } }
</style>
