<script setup lang="ts">
import { Info } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

/**
 * PageToolbar —— 页头下方的一条功能行：筛选 / 读数 / 操作。
 *
 * 不再是满幅的灰底工具条，而是一排「浮在画布上的控件」：透明底、无边框，只靠控件本身分组。
 * 筛选控件在左；读数（HeaderStat）与操作在右。`note` 只渲染一枚 ⓘ。
 *
 * 窄屏按内容自然换行，不为每组控件强占一整行。
 */
withDefaults(
  defineProps<{
    /** 一句口径说明；只渲染成一枚 ⓘ，全文在 tooltip 里 */
    note?: string
    /** 紧凑档：给 Tab 页或次级页用 */
    dense?: boolean
    /** 兼容旧调用；现在工具条本来就没有底线 */
    seamless?: boolean
    /** 把工具条装进一张面板（带边框与底色）；用在没有页头的页面上 */
    framed?: boolean
  }>(),
  { dense: false, seamless: false, framed: false },
)
</script>

<template>
  <div
    class="page-toolbar"
    :class="{ 'page-toolbar--dense': dense, 'page-toolbar--framed': framed }"
  >
    <div v-if="$slots.default" class="page-toolbar__filters">
      <slot />
    </div>

    <div v-if="$slots.stats" class="page-toolbar__stats" :class="{ 'ml-auto': $slots.default }">
      <slot name="stats" />
    </div>

    <div
      v-if="$slots.actions"
      class="page-toolbar__actions"
      :class="{ 'ml-auto': !$slots.stats }"
    >
      <slot name="actions" />
    </div>
    <Tooltip v-if="note">
      <TooltipTrigger as-child>
        <Button access="read"
          variant="ghost"
          size="icon-sm"
          class="page-toolbar__note"
          :class="{ 'ml-auto': !$slots.default && !$slots.stats && !$slots.actions }"
          aria-label="口径说明"
        >
          <Info />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">{{ note }}</TooltipContent>
    </Tooltip>
  </div>
</template>

<style scoped>
.page-toolbar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  min-width: 0;
  min-height: var(--ctl-h);
  padding: var(--gap-2) 0;
}

.page-toolbar--dense {
  min-height: var(--ctl-h-sm);
  padding: var(--gap-2) 0;
}

/* Wrapped schema filters keep actions alongside the final row of controls. */
.page-toolbar:has(:deep(.basic-form)) {
  align-items: flex-end;
}

.page-toolbar--framed {
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}

.page-toolbar__filters {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
  max-width: 100%;
}

.page-toolbar__filters > :deep(*) {
  max-width: 100%;
}

.page-toolbar__stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-4);
  min-width: 0;
}

.page-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.page-toolbar__note {
  margin: 0;
  color: var(--text-tertiary);
}

@media (max-width: 640px) {
  .page-toolbar {
    gap: var(--gap-2);
    padding: var(--gap-2) 0;
  }

  .page-toolbar__filters {
    flex: 1 1 auto;
    gap: 6px;
  }

  .page-toolbar__stats {
    flex: 0 1 auto;
    gap: var(--gap-2) var(--gap-3);
  }

  .page-toolbar__actions {
    flex: 0 1 auto;
    flex-wrap: wrap;
    gap: 6px;
    margin-left: auto;
  }

  .page-toolbar__actions::-webkit-scrollbar {
    display: none;
  }

  .page-toolbar__actions > :deep(*) {
    flex-shrink: 0;
  }
}
</style>
