<script setup lang="ts">
import { useAttrs, useId, type StyleValue } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../dialog'
import { cssLength } from './context'
import { usePanelLifecycle } from './usePanelLifecycle'
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: boolean; title?: string; width?: number | string; modal?: boolean; showClose?: boolean;
  closeOnClickModal?: boolean; closeOnPressEscape?: boolean; destroyOnClose?: boolean; alignCenter?: boolean;
  beforeClose?: (done: () => void) => void | Promise<void>
}>(), { modal: true, showClose: true, closeOnClickModal: true, closeOnPressEscape: true, width: 'min(760px, calc(100vw - 2rem))' })
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; opened: []; closed: []; close: [] }>()
const attrs = useAttrs()
const titleId = useId()
usePanelLifecycle(() => props.modelValue, event => {
  if (event === 'opened') emit('opened')
  else if (event === 'closed') emit('closed')
  else emit('close')
})
function update(value: boolean) {
  const done = () => {
    emit('update:modelValue', value)
  }
  if (!value && props.beforeClose) void props.beforeClose(done)
  else done()
}
</script>
<template>
  <Dialog :open="Boolean(modelValue)" :modal="modal" @update:open="update">
    <DialogContent v-bind="attrs" class="dialog-panel" :show-close-button="showClose" :show-overlay="modal"
      :style="[{ '--dialog-panel-w': cssLength(width) }, attrs.style as StyleValue]"
      @interact-outside="event => { if (!closeOnClickModal) event.preventDefault() }"
      @escape-key-down="event => { if (!closeOnPressEscape) event.preventDefault() }">
      <DialogHeader class="dialog-panel__header">
        <DialogTitle v-if="$slots.header" as-child>
          <div class="dialog-panel__title"><slot name="header" :close="() => update(false)" :title-id="titleId" title-class="dialog-panel__title" /></div>
        </DialogTitle>
        <DialogTitle v-else class="dialog-panel__title">{{ title || attrs['aria-label'] || '详情' }}</DialogTitle>
        <DialogDescription class="sr-only">{{ title || '详情与操作' }}</DialogDescription>
      </DialogHeader>
      <div class="dialog-panel__body"><slot /></div>
      <DialogFooter v-if="$slots.footer" class="dialog-panel__footer"><slot name="footer" /></DialogFooter>
    </DialogContent>
  </Dialog>
</template>
