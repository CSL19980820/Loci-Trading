<script setup lang="ts">
import type { DialogOverlayProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { DialogOverlay } from "reka-ui"
import { cn } from '@/shared/lib/utils'

/* 遮罩：半透明墨色 + 轻微模糊（Linear / Raycast 一路），深色档更重一点 */
const props = defineProps<DialogOverlayProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")
</script>

<template>
  <DialogOverlay
    data-slot="dialog-overlay"
    v-bind="delegatedProps"
    :class="cn('data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-[var(--z-popup)] bg-[oklch(0.15_0.02_255/0.45)] backdrop-blur-[3px] dark:bg-[oklch(0.05_0.01_255/0.7)]', props.class)"
  >
    <slot />
  </DialogOverlay>
</template>
