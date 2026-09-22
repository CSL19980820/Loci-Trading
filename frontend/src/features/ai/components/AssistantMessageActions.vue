<script setup lang="ts">
import { Copy, RefreshCw } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'

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
    <Button
      variant="ghost"
      size="sm"
      class="assistant-msg-actions__btn"
      data-testid="assistant-msg-copy"
      @click="emit('copy')"
    >
      <Copy aria-hidden="true" />
      复制
    </Button>
    <Button
      v-if="showRerun"
      variant="ghost"
      size="sm"
      class="assistant-msg-actions__btn"
      :disabled="disabled"
      data-testid="assistant-msg-rerun"
      @click="emit('rerun')"
    >
      <RefreshCw aria-hidden="true" />
      {{ rerunLabel }}
    </Button>
  </div>
</template>

<style scoped>
.assistant-msg-actions__btn { color: var(--mist); font-size: var(--ai-fs-body); }
.assistant-msg-actions__btn:hover { color: var(--ink); background: var(--surface-hover); }
.assistant-msg-actions__btn:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
</style>
