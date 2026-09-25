<script setup lang="ts">
import { Badge } from '@/shared/components/ui/badge'
/**
 * Sheet —— 区块壳。去卡片化：无阴影、1px hairline、圆角 3px（皮肤在 style.components.css）。
 * 头部一行：左标题（14px/700/字距 .03em）+ chip，右侧 actions；`meta` 槽放 12px 弱色口径。
 */
withDefaults(
  defineProps<{
    title?: string
    chip?: string | number
    mutedChip?: boolean
    quiet?: boolean
    /** 无外边框（内容区顶栏筛选等场景） */
    plain?: boolean
    padded?: boolean
    margin?: boolean
    /** 吃满弹性父级剩余高度，表体/图在 sheet-slot 内层滚 */
    fill?: boolean
  }>(),
  {
    mutedChip: false,
    quiet: false,
    plain: false,
    padded: false,
    margin: false,
    fill: false,
  },
)
</script>

<template>
  <!-- 区块壳：无阴影、1px hairline、圆角（D3）。plain=无框透明（筛选条）；quiet=弱标题 -->
  <section
    class="sheet border-line bg-surface overflow-hidden rounded-md shadow-none"
    :class="[
      { 'sheet-plain rounded-none border-0 bg-transparent': plain },
      margin ? 'mb-2' : '',
      fill ? 'sheet-fill flex h-full min-h-0 flex-1 flex-col' : '',
    ]"
  >
    <header
      v-if="title || $slots.header || $slots.actions || $slots.meta"
      class="sheet-bar border-line bg-surface flex min-h-[var(--head-h)] flex-wrap items-center justify-between gap-x-2 gap-y-1 border-b px-[var(--pad-sheet-x)] py-1"
      :class="{ 'quiet-bar': quiet }"
    >
      <slot name="header">
        <h2 class="m-0 flex min-w-0 flex-wrap items-center gap-2 font-sans text-title leading-tight font-bold">
          {{ title }}
          <Badge :variant="mutedChip ? 'secondary' : 'soft'" v-if="chip != null && chip !== ''" class="chip bg-seal-soft text-seal-ink inline-flex items-center rounded px-1 font-mono text-aux leading-normal font-semibold tabular-nums" :class="{ 'muted-chip bg-sunken text-mist font-medium': mutedChip }">{{ chip }}</Badge>
        </h2>
      </slot>
      <div v-if="$slots.meta || $slots.actions" class="flex min-w-0 flex-wrap items-center gap-2">
        <span v-if="$slots.meta" class="sheet-meta text-mist max-w-full truncate font-mono text-aux tabular-nums"><slot name="meta" /></span>
        <div v-if="$slots.actions" class="sheet-actions flex flex-wrap items-center gap-1">
          <slot name="actions" />
        </div>
      </div>
    </header>
    <div
      class="sheet-slot min-w-0"
      :class="{
        'sheet-body p-[var(--pad-sheet-y)_var(--pad-sheet-x)]': padded,
        'flex min-h-0 flex-1 flex-col overflow-hidden': fill,
      }"
    >
      <slot />
    </div>
  </section>
</template>
