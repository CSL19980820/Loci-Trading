<script setup lang="ts">
import { ArrowDown, LoaderCircle } from '@lucide/vue'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'

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

/** 破坏性操作用印章红（--stamp），不用涨跌红：删除和「涨」不该是同一个红 */
function variantOf(kind: HeaderAction['kind']): 'default' | 'outline' {
  return kind === 'primary' ? 'default' : 'outline'
}
</script>

<template>
  <div class="header-actions">
    <Button
      v-for="action in visibleSecondary"
      :key="action.key"
      size="sm"
      :variant="variantOf(action.kind)"
      :class="action.kind === 'danger' ? 'header-actions__danger' : ''"
      :disabled="action.disabled || action.loading"
      @click="run(action)"
    >
      <LoaderCircle v-if="action.loading" class="animate-spin" aria-hidden="true" />
      {{ action.label }}
    </Button>

    <DropdownMenu v-if="needsOverflow">
      <DropdownMenuTrigger as-child>
        <Button size="sm" variant="outline">
          更多
          <ArrowDown class="header-actions__caret" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          v-for="action in overflowActions"
          :key="action.key"
          :disabled="action.disabled || action.loading"
          :variant="action.kind === 'danger' ? 'destructive' : 'default'"
          @select="run(action)"
        >
          {{ action.label }}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>

    <Button
      v-for="action in primaryActions"
      :key="action.key"
      size="sm"
      variant="default"
      :disabled="action.disabled || action.loading"
      @click="run(action)"
    >
      <LoaderCircle v-if="action.loading" class="animate-spin" aria-hidden="true" />
      {{ action.label }}
    </Button>
  </div>
</template>

<style scoped>
.header-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  min-width: 0;
  gap: var(--gap-2);
}

/*
 * 主操作按钮的文字色由 Button 的 `text-primary-foreground` 给（= 本仓 `--on-primary`，
 * theme.ts 按主色 OKLCH 亮度定黑白）。写死 #fff 会在浅主色下失效。
 */
.header-actions__danger {
  border-color: color-mix(in oklab, var(--stamp) 45%, var(--rule));
  color: var(--stamp);
}

.header-actions__caret {
  width: var(--fs-kicker);
  height: var(--fs-kicker);
  opacity: 0.75;
}
</style>
