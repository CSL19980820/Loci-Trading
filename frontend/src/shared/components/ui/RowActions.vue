<script setup lang="ts">
import { computed } from 'vue'
import { useVisitorMode, type ControlAccess } from '@/shared/composables/useAccess'
import { Ellipsis } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

export interface RowAction {
  access?: ControlAccess
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

const visitor = useVisitorMode()
const permitted = computed(() => props.actions.filter(action => !visitor.value || action.access === 'read'))
const primary = computed(() => permitted.value.slice(0, props.maxVisible))
const extra = computed(() => permitted.value.slice(props.maxVisible))

function isDanger(action: RowAction): boolean {
  return action.type === 'danger'
}

/*
 * 行内动作是「小号文字按钮」：控件高 28px，字 12px；主色文字，危险用印章红。
 * 「更多」是一枚 ⋯ 图标按钮（Linear / Notion 风），不再是一个文字按钮。
 */
const ACTION_CLASS = 'row-actions__btn h-[var(--ctl-h-sm)] px-2 text-aux font-medium text-seal-ink hover:bg-seal-soft hover:text-seal-ink'
const DANGER_CLASS = 'row-actions__btn h-[var(--ctl-h-sm)] px-2 text-aux font-medium text-stamp hover:bg-stamp-soft hover:text-stamp'

function onMore(key: string): void {
  const action = extra.value.find((item) => item.key === key)
  if (!action || action.disabled) return
  action.onClick()
}
</script>

<template>
  <div class="row-actions inline-flex flex-nowrap items-center justify-end gap-0.5 whitespace-nowrap" @click.stop>
    <Tooltip v-for="action in primary" :key="action.key" :disabled="!action.disabled || !action.tip">
      <TooltipTrigger as-child>
        <span class="inline-flex items-center">
   <Button :access="action.access"
     variant="ghost"
     size="sm"
     :class="isDanger(action) ? DANGER_CLASS : ACTION_CLASS"
     :disabled="action.disabled"
     @click="action.onClick"
   >
     {{ action.label }}
   </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>{{ action.tip }}</TooltipContent>
    </Tooltip>

    <DropdownMenu v-if="extra.length">
      <DropdownMenuTrigger as-child>
        <Button access="read" variant="ghost" size="icon-sm" class="row-actions__more text-mist hover:text-ink" aria-label="更多操作">
   <Ellipsis />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <template v-for="(action, index) in extra" :key="action.key">
   <DropdownMenuSeparator v-if="action.divided && index > 0" />
   <DropdownMenuItem :access="action.access"
     :disabled="action.disabled"
     :variant="isDanger(action) ? 'destructive' : 'default'"
     @select="onMore(action.key)"
          >
            {{ action.label }}
   </DropdownMenuItem>
        </template>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
</template>
