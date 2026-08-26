<script setup lang="ts">
import type {
  ScreenSkillCatalog,
  ScreenSkillCatalogSnippet,
  ScreenSkillRuntime,
} from '@/shared/types/quant'

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
  <el-dialog
    v-model="visible"
    title="函数词典"
    width="min(920px, 92vw)"
    top="6vh"
    append-to-body
    destroy-on-close
    align-center
    class="catalog-dialog"
    modal-class="catalog-dialog-modal"
  >
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
  </el-dialog>
</template>

<style scoped>
.catalog-dialog__frame {
  height: min(560px, 72vh);
  min-height: 0;
  overflow: hidden;
}
</style>

<style>
/* el-dialog teleports to body；需非 scoped 才能锁死外层滚动 */
.catalog-dialog.el-dialog {
  margin-bottom: 0;
  overflow: hidden;
}

.catalog-dialog .el-dialog__body {
  padding: 0.35rem 1rem 1rem;
  overflow: hidden;
}

.catalog-dialog-modal {
  overflow: hidden;
}
</style>
