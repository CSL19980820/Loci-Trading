<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { X } from "@lucide/vue"
import { reactiveOmit } from "@vueuse/core"
import {
  DialogClose,
  DialogContent,
  DialogPortal,
  useForwardPropsEmits,
} from "reka-ui"
import { cn } from '@/shared/lib/utils'
import DialogOverlay from "./DialogOverlay.vue"

/*
 * 对话框：
 * 所有屏幕统一距顶 5dvh；内容限制在 90dvh 内，长表单内部滚动。
 * fullscreenMobile 保留调用兼容性，不再覆盖统一的顶部安全距离。
 */
defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<DialogContentProps & {
  class?: HTMLAttributes["class"]
  showCloseButton?: boolean
  showOverlay?: boolean
  fullscreenMobile?: boolean
}>(), {
  showCloseButton: true,
  showOverlay: true,
  fullscreenMobile: false,
})
const emits = defineEmits<DialogContentEmits>()

const delegatedProps = reactiveOmit(props, "class", "showCloseButton", "showOverlay", "fullscreenMobile")

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <DialogPortal>
    <DialogOverlay v-if="showOverlay" />
    <DialogContent
      data-slot="dialog-content"
      :data-mobile="fullscreenMobile ? 'full' : 'sheet'"
      v-bind="{ ...$attrs, ...forwarded }"
      :class="
        cn(
          'ui-dialog bg-raised text-ink fixed z-[var(--z-popup)] grid w-full gap-4 border border-line shadow-lg outline-none duration-200',
   'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
          'top-[5dvh] left-1/2 max-w-[calc(100vw-24px)] max-h-[90dvh] -translate-x-1/2 rounded-xl p-4 overflow-y-auto sm:max-w-lg sm:p-6',
          props.class,
        )"
    >
      <slot />

      <DialogClose
        v-if="showCloseButton"
        data-slot="dialog-close"
        class="ui-dialog__close ring-offset-background focus-visible:ring-ring/40 absolute top-3 right-3 inline-flex size-8 items-center justify-center rounded-md text-mist transition-colors hover:bg-hover hover:text-ink focus-visible:ring-3 focus-visible:outline-hidden disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
      >
 <X />
 <span class="sr-only">关闭</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>

<style scoped>
/* 手机端：网格内容可滚。DialogContent 是 grid，把「超出部分可滚」交给直接子级里最大的那个 */
.ui-dialog {
  grid-template-rows: auto;
  top: 5dvh;
  bottom: auto;
  translate: -50% 0;
  max-height: 90dvh;
  overscroll-behavior: contain;
}

@media (max-width: 640px) {
  .ui-dialog {
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
  }

  .ui-dialog__close {
    top: 10px;
    right: 10px;
  }
}

.ui-dialog__grip {
  position: absolute;
  top: 8px;
  left: 50%;
  width: 40px;
  height: 4px;
  border-radius: 999px;
  background: var(--border-strong);
  transform: translateX(-50%);
}
</style>
