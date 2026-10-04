<script setup lang="ts">
import type { DialogRootEmits, DialogRootProps } from "reka-ui"
import { computed, inject, nextTick, onActivated, onDeactivated, provide, ref, watch } from "vue"
import { DialogRoot, useForwardProps } from "reka-ui"
import { dialogVisibilityKey } from "./dialogVisibility"

const props = withDefaults(defineProps<DialogRootProps>(), { open: undefined })
const emits = defineEmits<DialogRootEmits>()

const forwarded = useForwardProps(props)

// A cached route keeps its teleported content in body. Suspend the source page's
// dialogs while its archive is open, retaining their content and models so nested
// details are restored when the user returns.
const active = ref(true)
const uncontrolledOpen = ref(props.defaultOpen ?? false)
const parentVisible = inject(dialogVisibilityKey, null)
const parentReady = ref(parentVisible?.value ?? true)
onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false })
const visibleOpen = computed(() => active.value && parentReady.value && (props.open ?? uncontrolledOpen.value))
provide(dialogVisibilityKey, visibleOpen)

// Restore the parent first, then its nested dialog, so the innermost modal keeps
// keyboard focus and remains the accessible layer after a cached-route return.
if (parentVisible) {
  watch(parentVisible, async visible => {
    parentReady.value = false
    if (!visible) return
    await nextTick()
    if (parentVisible.value) parentReady.value = true
  })
}

function updateOpen(value: boolean): void {
  if (!active.value) return
  uncontrolledOpen.value = value
  emits('update:open', value)
}
</script>

<template>
  <DialogRoot
    v-slot="slotProps"
    data-slot="dialog"
    v-bind="forwarded"
    :open="visibleOpen"
    :unmount-on-hide="active ? forwarded.unmountOnHide ?? true : false"
    @update:open="updateOpen"
  >
    <slot v-bind="slotProps" />
  </DialogRoot>
</template>
