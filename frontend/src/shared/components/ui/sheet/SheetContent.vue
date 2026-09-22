<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { X } from '@lucide/vue'
import { reactiveOmit } from '@vueuse/core'
import { DialogClose, DialogContent, DialogPortal, useForwardPropsEmits } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
import SheetOverlay from './SheetOverlay.vue'

interface SheetContentProps extends DialogContentProps {
  class?: HTMLAttributes['class']
  side?: 'top' | 'right' | 'bottom' | 'left'
}
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<SheetContentProps>(), { side: 'right' })
const emits = defineEmits<DialogContentEmits>()
const forwarded = useForwardPropsEmits(reactiveOmit(props, 'class', 'side'), emits)
</script>
<template>
  <DialogPortal>
    <SheetOverlay />
    <DialogContent data-slot="sheet-content" :data-side="side" v-bind="{ ...$attrs, ...forwarded }"
      :class="cn('ui-sheet bg-raised text-ink fixed z-[var(--z-popup)] flex flex-col gap-4 border border-line shadow-lg outline-none rounded-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 duration-200', props.class)">
      <slot />
      <DialogClose class="ui-sheet__close ring-offset-background focus-visible:ring-ring/40 absolute top-3 right-3 inline-flex size-8 items-center justify-center rounded-md text-mist transition-colors hover:bg-hover hover:text-ink focus-visible:ring-3 focus-visible:outline-hidden disabled:pointer-events-none">
        <X class="size-4" /><span class="sr-only">关闭</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
<style scoped>
/* 与普通弹窗共享顶部安全距离，侧板正文负责滚动。 */
.ui-sheet { top:5dvh; bottom:auto; right:12px; width:480px; max-width:calc(100vw - 24px); height:90dvh; max-height:90dvh; overflow-y:auto; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; }
.ui-sheet[data-side='left'] { left:12px; right:auto; }
.ui-sheet[data-side='top'],.ui-sheet[data-side='bottom'] { left:12px; right:12px; width:auto; height:auto; }
@media(max-width:640px) {
  .ui-sheet,.ui-sheet[data-side='left'] { left:12px; right:12px; width:calc(100vw - 24px); max-width:calc(100vw - 24px); padding-bottom:env(safe-area-inset-bottom); }
}
</style>
