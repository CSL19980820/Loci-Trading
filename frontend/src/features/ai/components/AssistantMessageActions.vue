<script setup lang="ts">
import { CopyDocument, RefreshRight } from '@element-plus/icons-vue'

defineProps<{
  /** 用户：重跑；助手：重新生成 */
  rerunLabel: string
  showRerun?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  copy: []
  rerun: []
}>()
</script>

<template>
  <div class="assistant-msg-actions" data-testid="assistant-msg-actions">
    <el-button
      class="assistant-msg-actions__btn"
      text
      size="small"
      :icon="CopyDocument"
      data-testid="assistant-msg-copy"
      @click="emit('copy')"
    >
      复制
    </el-button>
    <el-button
      v-if="showRerun"
      class="assistant-msg-actions__btn"
      text
      size="small"
      :icon="RefreshRight"
      :disabled="disabled"
      data-testid="assistant-msg-rerun"
      @click="emit('rerun')"
    >
      {{ rerunLabel }}
    </el-button>
  </div>
</template>

<style scoped>
.assistant-msg-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.1rem;
  margin-top: 0.2rem;
  opacity: 0.72;
  transition: opacity 0.15s ease;
}
.assistant-turn:hover .assistant-msg-actions,
.assistant-msg-actions:focus-within {
  opacity: 1;
}
.assistant-msg-actions__btn {
  --el-button-text-color: var(--mist);
  --el-button-hover-text-color: var(--ink);
  height: 1.55rem;
  padding: 0 0.35rem;
  font-size: var(--ai-fs-aux);
}
@media (hover: none) {
  .assistant-msg-actions { opacity: 1; }
}
</style>
