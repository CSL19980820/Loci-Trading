<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { DialogClose } from "reka-ui"
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/components/ui/button'

/*
 * 页脚：桌面右对齐一行；手机端按钮全宽、主操作在上（flex-col-reverse 让 DOM 顺序仍是「取消 → 确认」）。
 * 手机端粘在 sheet 底部，避免长表单把按钮推出视口。
 */
const props = withDefaults(defineProps<{
  class?: HTMLAttributes["class"]
  showCloseButton?: boolean
}>(), {
  showCloseButton: false,
})
</script>

<template>
  <div
    data-slot="dialog-footer"
    :class="cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end max-sm:sticky max-sm:bottom-0 max-sm:-mx-4 max-sm:-mb-[max(env(safe-area-inset-bottom),16px)] max-sm:border-t max-sm:border-line max-sm:bg-raised max-sm:px-4 max-sm:pt-3 max-sm:pb-[max(env(safe-area-inset-bottom),16px)] max-sm:[&>button]:h-11 max-sm:[&>button]:w-full', props.class)"
  >
    <slot />
    <DialogClose v-if="showCloseButton" as-child>
      <Button access="read" variant="outline">关闭</Button>
    </DialogClose>
  </div>
</template>
