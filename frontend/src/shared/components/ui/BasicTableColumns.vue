<script setup lang="ts">
import BasicTableCell from './BasicTableCell.vue'
import type { BasicTableColumn } from './basicTableTypes'

defineOptions({ name: 'BasicTableColumns' })

defineProps<{
  columns: BasicTableColumn[]
  isEditing: (row: Record<string, unknown>) => boolean
}>()

const emit = defineEmits<{
  'update:field': [row: Record<string, unknown>, prop: string, value: unknown]
}>()

function onField(row: Record<string, unknown>, prop: string, value: unknown): void {
  emit('update:field', row, prop, value)
}
</script>

<template>
  <template v-for="(col, idx) in columns" :key="col.prop ?? col.type ?? col.label ?? idx">
    <el-table-column
      v-if="!col.hidden && (col.type === 'selection' || col.type === 'index' || col.type === 'expand')"
      :type="col.type"
      :width="col.width"
      :label="col.label"
      :align="col.align ?? 'center'"
      :header-align="col.headerAlign ?? 'center'"
      :fixed="col.fixed"
    />
    <el-table-column
      v-else-if="!col.hidden && col.children?.length"
      :label="col.label"
      :align="col.align ?? 'center'"
      :header-align="col.headerAlign ?? 'center'"
    >
      <BasicTableColumns
        :columns="col.children"
        :is-editing="isEditing"
        @update:field="onField"
      />
    </el-table-column>
    <el-table-column
      v-else-if="!col.hidden"
      :prop="col.prop"
      :label="col.label"
      :width="col.width"
      :min-width="col.minWidth"
      :align="col.align ?? 'center'"
      :header-align="col.headerAlign ?? 'center'"
      :fixed="col.fixed"
      :sortable="col.sortable"
      :show-overflow-tooltip="col.showOverflowTooltip"
      :filters="col.filters"
      :filter-multiple="col.filterMultiple"
      :filter-placement="col.filterPlacement"
      :filter-method="col.filterMethod
        ? (value: unknown, row: Record<string, unknown>, column: unknown) =>
            col.filterMethod!(value, row, column)
        : undefined"
    >
      <template #default="scope">
        <BasicTableCell
          :col="col"
          :row="scope.row as Record<string, unknown>"
          :index="scope.$index"
          :editing="isEditing(scope.row as Record<string, unknown>) && !!col.editRender"
          @update:field="(prop, value) => onField(scope.row as Record<string, unknown>, prop, value)"
        />
      </template>
    </el-table-column>
  </template>
</template>
