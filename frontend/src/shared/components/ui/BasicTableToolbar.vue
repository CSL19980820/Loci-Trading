<script setup lang="ts">
import { RefreshCw as RefreshRight, Settings as Setting } from '@lucide/vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as PopoverPanel } from '@/shared/components/ui/app/PopoverPanel.vue'
import { default as CheckboxField } from '@/shared/components/ui/app/CheckboxField.vue'

/**
 * BasicTable 的工具行：刷新 / 放大 / 列设置，外加左侧 `#buttons` 槽。
 *
 * 它是表里唯一一块「与数据无关」的 UI：三颗按钮各自独立，列设置还带一个会
 * teleport 到 body 的弹层。留在 BasicTable 里时，这段模板与它的一堆按钮皮肤
 * 覆盖夹在表体和分页器中间，读表格渲染的人得先跳过它。
 *
 * 根节点必须保留 `.basic-table__toolbar` 类：JobRecentRunsPanel / JobRunsDialog /
 * ScreenHistoryPanel 三处页面用 `:deep(.basic-table__toolbar)` 调它的内外边距。
 *
 * 列设置直接改 `columns` 元素上的 `hidden`：数组是父层传下来的同一个响应式代理，
 * 就地写字段即可回流，不必再往上抛事件（与 GridEngine 的口径一致）。
 */
import { computed } from 'vue'


import type { BasicTableColumn, BasicTableToolbarConfig } from './basicTableTypes'

const props = defineProps<{
  config?: BasicTableToolbarConfig
  columns: BasicTableColumn[]
  busy?: boolean
}>()

const emit = defineEmits<{ refresh: [] }>()

const zoomed = defineModel<boolean>('zoomed', { default: false })

const customizableColumns = computed(() =>
  props.columns.filter((c) => c.type !== 'selection' && c.type !== 'index' && c.type !== 'expand'),
)
</script>

<template>
  <div class="basic-table__toolbar flex w-full shrink-0 items-center justify-start gap-2 border-b px-[var(--pad-sheet-x)] py-2">
    <div class="basic-table__toolbar-left ml-auto flex flex-wrap items-center gap-2">
      <slot name="buttons" />
    </div>
    <div class="basic-table__toolbar-right flex flex-wrap items-center gap-2">
      <ActionButton access="read"
        v-if="config?.refresh"
        size="small"
        :icon="RefreshRight"
        :busy="busy"
        @click="emit('refresh')"
      >
        刷新
      </ActionButton>
      <ActionButton access="read"
        v-if="config?.zoom"
        size="small"
        @click="zoomed = !zoomed"
      >
        {{ zoomed ? '还原' : '放大' }}
      </ActionButton>
      <PopoverPanel
        v-if="config?.custom"
        placement="bottom-end"
        :width="200"
        trigger="click"
      >
        <template #reference>
          <ActionButton access="read" size="small" :icon="Setting">列设置</ActionButton>
        </template>
        <div class="basic-table__cols">
          <CheckboxField
            v-for="(col, i) in customizableColumns"
            :key="col.prop ?? col.label ?? i"
            :model-value="!col.hidden"
            @change="(v: string | number | boolean) => { col.hidden = !v }"
          >
            {{ col.label || col.prop || `列${i + 1}` }}
          </CheckboxField>
        </div>
      </PopoverPanel>
    </div>
  </div>
</template>

<style scoped>
.basic-table__toolbar {
  border-bottom: 1px solid var(--border-subtle);
  background: transparent;
}

.basic-table__toolbar-left :deep(.action-button),
.basic-table__toolbar-right :deep(.action-button) {
  margin: 0;
}

.basic-table__toolbar-left :deep(.action-button + .action-button),
.basic-table__toolbar-right :deep(.action-button + .action-button) {
  margin-left: 0;
}

.basic-table__cols {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  max-height: 16rem;
  overflow: auto;
}
</style>
