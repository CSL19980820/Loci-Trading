<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

export type HeaderAction = {
  key: string
  label: string
  /** primary 始终外露；其余占可见名额，超出进「更多」 */
  kind?: 'primary' | 'secondary' | 'danger'
  loading?: boolean
  disabled?: boolean
  /** 路由跳转（优先于 onClick） */
  to?: string
  onClick?: () => void
}

const props = withDefaults(
  defineProps<{
    actions: HeaderAction[]
    /** 含主按钮与「更多」在内的最大外露数，默认 4 */
    maxVisible?: number
  }>(),
  { maxVisible: 4 },
)

const router = useRouter()

const primaryActions = computed(() => props.actions.filter((a) => a.kind === 'primary'))
const secondaryActions = computed(() => props.actions.filter((a) => a.kind !== 'primary'))

const secondaryBudget = computed(() => Math.max(0, props.maxVisible - primaryActions.value.length))

const needsOverflow = computed(() => secondaryActions.value.length > secondaryBudget.value)

const visibleSecondary = computed(() => {
  if (!needsOverflow.value) return secondaryActions.value
  return secondaryActions.value.slice(0, Math.max(0, secondaryBudget.value - 1))
})

const overflowActions = computed(() => {
  if (!needsOverflow.value) return []
  return secondaryActions.value.slice(Math.max(0, secondaryBudget.value - 1))
})

function run(action: HeaderAction): void {
  if (action.disabled || action.loading) return
  if (action.to) {
    void router.push(action.to)
    return
  }
  action.onClick?.()
}

function onMore(key: string): void {
  const action = overflowActions.value.find((a) => a.key === key)
  if (action) run(action)
}

function buttonType(kind: HeaderAction['kind']): '' | 'primary' | 'danger' {
  if (kind === 'primary') return 'primary'
  if (kind === 'danger') return 'danger'
  return ''
}
</script>

<template>
  <div class="header-actions">
    <el-button
      v-for="action in visibleSecondary"
      :key="action.key"
      size="small"
      :type="buttonType(action.kind)"
      :plain="action.kind === 'danger'"
      :loading="action.loading"
      :disabled="action.disabled"
      @click="run(action)"
    >
      {{ action.label }}
    </el-button>

    <el-dropdown v-if="needsOverflow" trigger="click" @command="onMore">
      <el-button size="small">
        更多
        <span class="header-actions__caret" aria-hidden="true">▾</span>
      </el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="action in overflowActions"
            :key="action.key"
            :command="action.key"
            :disabled="action.disabled"
          >
            {{ action.label }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <el-button
      v-for="action in primaryActions"
      :key="action.key"
      size="small"
      type="primary"
      :loading="action.loading"
      :disabled="action.disabled"
      @click="run(action)"
    >
      {{ action.label }}
    </el-button>
  </div>
</template>

<style scoped>
.header-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--gap-2);
}

.header-actions :deep(.el-button) {
  margin: 0;
  background: var(--sheet);
  border-color: var(--rule-strong);
  color: var(--ink);
}

/*
 * 主操作按钮的文字色必须跟 --on-primary（theme.ts 按主色 OKLCH 亮度定黑白）。
 * 写死 #fff 会在浅主色下失效：amber 档 #fff/#d79700 只有 2.53:1，远低于 AA 的 4.5:1。
 */
.header-actions :deep(.el-button--primary) {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  color: var(--on-primary);
}

/* 破坏性操作用印章红（--stamp），不用涨跌红：删除和「涨」不该是同一个红 */
.header-actions :deep(.el-button--danger.is-plain) {
  background: transparent;
  border-color: color-mix(in srgb, var(--stamp) 45%, var(--rule));
  color: var(--stamp);
}

.header-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.header-actions__caret {
  margin-left: var(--gap-1);
  font-size: var(--fs-kicker);
  opacity: 0.75;
}
</style>
