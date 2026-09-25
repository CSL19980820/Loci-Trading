<script setup lang="ts">
import { Copy, RefreshCw } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { MessageFooter } from '@/shared/components/ui/message'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

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
  <MessageFooter class="assistant-msg-actions" data-testid="assistant-msg-actions">
    <Tooltip><TooltipTrigger as-child>
    <Button
      access="read"
      variant="ghost"
      size="icon-sm"
      class="assistant-msg-actions__btn"
      aria-label="复制"
      data-testid="assistant-msg-copy"
      @click="emit('copy')"
    >
      <Copy aria-hidden="true" />
    </Button>
    </TooltipTrigger><TooltipContent>复制</TooltipContent></Tooltip>
    <Tooltip v-if="showRerun"><TooltipTrigger as-child>
    <Button
      variant="ghost"
      size="icon-sm"
      class="assistant-msg-actions__btn"
      :aria-label="rerunLabel"
      :disabled="disabled"
      data-testid="assistant-msg-rerun"
      @click="emit('rerun')"
    >
      <RefreshCw aria-hidden="true" />
    </Button>
    </TooltipTrigger><TooltipContent>{{ rerunLabel }}</TooltipContent></Tooltip>
  </MessageFooter>
</template>

<style scoped>
.assistant-msg-actions { gap:2px; padding:0; margin-top:2px; }
.assistant-msg-actions__btn { color: var(--text-tertiary); width:32px; height:32px; border-radius:8px; }
.assistant-msg-actions__btn :deep(svg) { width:15px; height:15px; }
.assistant-msg-actions__btn:hover { color: var(--ink); background: var(--surface-hover); }
.assistant-msg-actions__btn:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
@media (pointer:coarse) { .assistant-msg-actions__btn { width:36px; height:36px; } }
</style>
