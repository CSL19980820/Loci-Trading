<script setup lang="ts">
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
 * 就地写字段即可回流，不必再往上抛事件（与 BasicTableColumns 的口径一致）。
 */
import { computed } from 'vue'
import { RefreshRight, Setting } from '@element-plus/icons-vue'

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
  <div class="basic-table__toolbar">
    <div class="basic-table__toolbar-left">
      <slot name="buttons" />
    </div>
    <div class="basic-table__toolbar-right">
      <el-button
        v-if="config?.refresh"
        size="small"
        :icon="RefreshRight"
        :loading="busy"
        @click="emit('refresh')"
      >
        刷新
      </el-button>
      <el-button
        v-if="config?.zoom"
        size="small"
        @click="zoomed = !zoomed"
      >
        {{ zoomed ? '还原' : '放大' }}
      </el-button>
      <el-popover
        v-if="config?.custom"
        placement="bottom-end"
        :width="200"
        trigger="click"
      >
        <template #reference>
          <el-button size="small" :icon="Setting">列设置</el-button>
        </template>
        <div class="basic-table__cols">
          <el-checkbox
            v-for="(col, i) in customizableColumns"
            :key="col.prop ?? col.label ?? i"
            :model-value="!col.hidden"
            @change="(v: string | number | boolean) => { col.hidden = !v }"
          >
            {{ col.label || col.prop || `列${i + 1}` }}
          </el-checkbox>
        </div>
      </el-popover>
    </div>
  </div>
</template>

<style scoped>
.basic-table__toolbar {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-1) var(--pad-sheet-x);
  border-bottom: 1px solid var(--rule);
  background: var(--sheet-alt);
  flex-shrink: 0;
}

.basic-table__toolbar-left,
.basic-table__toolbar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.basic-table__toolbar-right {
  margin-left: auto;
}

.basic-table__toolbar-left :deep(.el-button),
.basic-table__toolbar-right :deep(.el-button) {
  margin: 0;
}

.basic-table__toolbar-left :deep(.el-button + .el-button),
.basic-table__toolbar-right :deep(.el-button + .el-button) {
  margin-left: 0;
}

.basic-table__toolbar-right :deep(.el-button) {
  --el-button-bg-color: var(--sheet);
  --el-button-border-color: var(--rule-strong);
  --el-button-text-color: var(--ink);
  --el-button-hover-bg-color: var(--sheet-alt);
  --el-button-hover-border-color: var(--rule-strong);
  --el-button-hover-text-color: var(--ink);
}

.basic-table__cols {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  max-height: 16rem;
  overflow: auto;
}
</style>
