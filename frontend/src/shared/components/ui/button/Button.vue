<script setup lang="ts">
import type { PrimitiveProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import type { ButtonVariants } from "."
import { Primitive } from "reka-ui"
import { cn } from '@/shared/lib/utils'
import { buttonVariants } from "."
import { useVisitorMode, type ControlAccess } from '@/shared/composables/useAccess'

interface Props extends PrimitiveProps {
  /** Visitors must explicitly opt into reading/navigation controls. */
  access?: ControlAccess
  variant?: ButtonVariants["variant"]
  size?: ButtonVariants["size"]
  class?: HTMLAttributes["class"]
}

const props = withDefaults(defineProps<Props>(), {
  as: "button",
})
const visitor = useVisitorMode()
</script>

<template>
  <Primitive
    v-if="!visitor || access === 'read'"
    data-slot="button"
    :data-variant="variant ?? 'default'"
    :data-size="size"
    :as="as"
    :as-child="asChild"
    :class="cn(buttonVariants({ variant, size }), props.class)"
  >
    <slot />
  </Primitive>
</template>
