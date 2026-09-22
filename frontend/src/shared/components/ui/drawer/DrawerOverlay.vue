<script lang="ts" setup>
import type { DrawerOverlayProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { DrawerOverlay } from "reka-ui"
import { cn } from '@/shared/lib/utils'

const props = defineProps<DrawerOverlayProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")
</script>

<template>
  <DrawerOverlay
    data-slot="drawer-overlay"
    v-bind="delegatedProps"
    :class="cn('data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-[var(--z-popup)] bg-[oklch(0.15_0.02_255/0.45)] backdrop-blur-[3px] duration-300 dark:bg-[oklch(0.05_0.01_255/0.7)]', props.class)"
  />
</template>
