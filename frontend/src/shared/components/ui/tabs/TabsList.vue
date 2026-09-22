<script setup lang="ts">
import type { TabsListProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { TabsList } from "reka-ui"
import { cn } from '@/shared/lib/utils'

/* 药片分段：下沉底、3px 内边距，选中项浮起成白片 */
const props = defineProps<TabsListProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")
</script>

<template>
  <TabsList
    data-slot="tabs-list"
    v-bind="delegatedProps"
    :class="cn(
      'bg-sunken text-muted-foreground inline-flex h-[var(--ctl-h)] w-fit items-center justify-center gap-0.5 rounded-md p-[3px]',
      props.class,
    )"
  >
    <slot />
  </TabsList>
</template>
