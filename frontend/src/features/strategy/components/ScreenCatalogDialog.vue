<script setup lang="ts">
import type {
  ScreenSkillCatalog,
  ScreenSkillCatalogSnippet,
  ScreenSkillRuntime,
} from '@/shared/types/quant'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'

import ScreenWorkbenchCatalog from './ScreenWorkbenchCatalog.vue'

const visible = defineModel<boolean>({ default: false })

defineProps<{
  catalog: ScreenSkillCatalog | null
  runtime?: ScreenSkillRuntime
  loading?: boolean
}>()

const emit = defineEmits<{
  insertText: [text: string]
  applySnippet: [snippet: ScreenSkillCatalogSnippet]
}>()

function onInsert(text: string): void {
  emit('insertText', text)
  visible.value = false
}

function onSnippet(snippet: ScreenSkillCatalogSnippet): void {
  emit('applySnippet', snippet)
  visible.value = false
}
</script>

<template>
  <Dialog v-model:open="visible">
    <DialogContent
      class="catalog-dialog w-[min(920px,92vw)] max-w-none gap-3 overflow-hidden p-4 sm:max-w-none"
    >
      <DialogHeader class="gap-1 text-left">
        <DialogTitle>函数词典</DialogTitle>
      </DialogHeader>
      <div class="catalog-dialog__frame">
        <ScreenWorkbenchCatalog
          :catalog="catalog"
          :runtime="runtime"
          :loading="loading"
          layout="dialog"
          @insert-text="onInsert"
          @apply-snippet="onSnippet"
        />
      </div>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.catalog-dialog__frame {
  height: min(560px, 72vh);
  min-height: 0;
  overflow: hidden;
}
</style>
