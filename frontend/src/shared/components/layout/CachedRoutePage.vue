<script setup lang="ts">
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, type Component } from 'vue'

defineProps<{ component: Component }>()
const root = ref<HTMLElement>()
const positions = new Map<HTMLElement, { top: number; left: number }>()
let suspended = false
let frame = 0
function remember(event: Event): void {
  const element = event.target
  if (suspended || !(element instanceof HTMLElement) || !element.isConnected || !root.value?.contains(element)) return
  positions.set(element, { top: element.scrollTop, left: element.scrollLeft })
}
onDeactivated(() => { suspended = true; cancelAnimationFrame(frame) })
onActivated(async () => {
  suspended = false
  await nextTick()
  frame = requestAnimationFrame(() => {
    if (suspended) return
    for (const [element, position] of positions) {
      if (root.value?.contains(element)) {
        element.scrollTop = position.top
        element.scrollLeft = position.left
      } else positions.delete(element)
    }
  })
})
onBeforeUnmount(() => { cancelAnimationFrame(frame); positions.clear() })
</script>

<template>
  <div ref="root" class="cached-route-page" @scroll.capture.passive="remember">
    <component :is="component" />
  </div>
</template>

<style scoped>
.cached-route-page { display:flex; flex-direction:column; flex:1 1 0%; min-width:0; min-height:0; width:100%; height:100%; overflow:hidden; }
</style>
