<script setup lang="ts">
import { computed, useAttrs, type StyleValue } from 'vue'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from '../sheet'
import { cssLength } from './context'
import { usePanelLifecycle } from './usePanelLifecycle'
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: boolean; title?: string; size?: string | number; direction?: string; closeOnClickModal?: boolean;
  closeOnPressEscape?: boolean; beforeClose?: (done: () => void) => void | Promise<void>; destroyOnClose?: boolean
}>(), { size: 'min(640px, 100vw)', direction: 'rtl', closeOnClickModal: true, closeOnPressEscape: true })
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; closed: []; opened: []; close: [] }>()
const attrs = useAttrs()
usePanelLifecycle(() => props.modelValue, event => {
  if (event === 'opened') emit('opened')
  else if (event === 'closed') emit('closed')
  else emit('close')
})
const side = computed(() => ({ rtl: 'right', ltr: 'left', btt: 'bottom', ttb: 'top' })[props.direction] as 'right' | 'left' | 'top' | 'bottom' || 'right')
function update(value: boolean) {
  const done = () => { emit('update:modelValue', value) }
  if (!value && props.beforeClose) void props.beforeClose(done)
  else done()
}
</script>
<template>
  <Sheet :open="Boolean(modelValue)" @update:open="update">
    <SheetContent v-bind="attrs" class="side-panel" :side="side"
      :style="[{ '--side-panel-w': side === 'right' || side === 'left' ? cssLength(size) : undefined }, attrs.style as StyleValue]"
      @interact-outside="event => { if (!closeOnClickModal) event.preventDefault() }"
      @escape-key-down="event => { if (!closeOnPressEscape) event.preventDefault() }">
      <SheetHeader class="side-panel__header"><SheetTitle>{{ title || '详情' }}</SheetTitle><SheetDescription class="sr-only">{{ title || '详情与操作' }}</SheetDescription></SheetHeader>
      <div class="side-panel__body"><slot /></div>
      <SheetFooter v-if="$slots.footer" class="side-panel__footer"><slot name="footer" /></SheetFooter>
    </SheetContent>
  </Sheet>
</template>
