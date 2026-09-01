<script setup lang="ts">
import { computed } from 'vue'

export interface RowAction {
  key: string
  label: string
  type?: 'primary' | 'danger' | 'success' | 'warning' | 'info'
  divided?: boolean
  /** 置灰但保留在原位：动作消失会让行与行的操作列错位，也让用户以为「没这个功能」 */
  disabled?: boolean
  /** 置灰的原因（≤14 字）。只在 disabled 时挂 tooltip，正常态不打扰 */
  tip?: string
  onClick: () => void
}

const props = withDefaults(
  defineProps<{
    actions: RowAction[]
    maxVisible?: number
  }>(),
  { maxVisible: 2 },
)

const primary = computed(() => props.actions.slice(0, props.maxVisible))
const extra = computed(() => props.actions.slice(props.maxVisible))

function onMore(key: string): void {
  const action = extra.value.find((item) => item.key === key)
  if (!action || action.disabled) return
  action.onClick()
}
</script>

<template>
  <div class="row-actions" @click.stop>
    <el-tooltip
      v-for="action in primary"
      :key="action.key"
      :content="action.tip || ''"
      :disabled="!action.disabled || !action.tip"
      placement="top"
      :show-after="200"
    >
      <span class="row-actions__slot">
        <el-button
          text
          :type="action.type || 'primary'"
          size="small"
          :disabled="action.disabled"
          @click="action.onClick"
        >
          {{ action.label }}
        </el-button>
      </span>
    </el-tooltip>
    <el-dropdown v-if="extra.length" trigger="click" @command="onMore">
      <el-button text size="small">更多</el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="action in extra"
            :key="action.key"
            :command="action.key"
            :divided="action.divided"
            :disabled="action.disabled"
          >
            {{ action.label }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.row-actions :deep(.el-button) {
  height: var(--ctl-h);
  margin: 0;
  padding: 0 var(--gap-1);
}

.row-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

/* 行内删除类动作同样走印章红，不借 EP 默认 danger 的橙红 */
.row-actions :deep(.el-button--danger.is-text) {
  --el-button-text-color: var(--stamp);
  --el-button-hover-text-color: var(--stamp);
  --el-button-hover-bg-color: color-mix(in srgb, var(--stamp) 8%, transparent);
}

.row-actions :deep(.el-dropdown) {
  margin-left: 0;
}

/* 置灰按钮外面那层 tooltip 触发器不能吃掉行高，否则操作列比别的列高 1~2px */
.row-actions__slot {
  display: inline-flex;
  align-items: center;
}
</style>
