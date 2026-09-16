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
  <div class="assistant-msg-actions mt-1 flex flex-wrap items-center gap-1" data-testid="assistant-msg-actions">
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
.assistant-msg-actions__btn { --el-button-text-color: var(--mist); --el-button-hover-text-color: var(--ink); --el-button-hover-bg-color: var(--surface-hover); height: var(--ctl-h); margin: 0; padding-inline: var(--gap-2); font-size: var(--ai-fs-body); }
.assistant-msg-actions__btn:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
</style>
