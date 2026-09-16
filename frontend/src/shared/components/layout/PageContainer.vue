<script setup lang="ts">
import { computed, useSlots } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 左侧区域宽度 */
    leftWidth?: string
    /** 容器内边距（纸色沟槽已在 main-content；此处多为内容卡内边距） */
    padding?: string
    /** 左右区域间距 */
    gap?: string
  }>(),
  {
    leftWidth: '230px',
    padding: '0',
    gap: 'var(--gap-2)',
  },
)

const slots = useSlots()
const hasLeft = computed(() => Boolean(slots.left))
const hasSearch = computed(() => Boolean(slots.search))
const hasMain = computed(() => Boolean(slots.main))
const hasTopExpand = computed(() => Boolean(slots.topExpand))
</script>

<template>
  <!-- 双栏页容器：左 rail + 右主区。高度链靠 flex 传递，滚动只在左栏/表体内 -->
  <div
    class="page-container relative flex h-full min-h-0 w-full flex-1 gap-[var(--pc-gap)] overflow-hidden p-[var(--pc-padding)]"
    :style="{
      '--pc-left-width': leftWidth,
      '--pc-padding': padding,
      '--pc-gap': gap,
    }"
  >
    <aside v-if="hasLeft" class="page-container__left bg-surface border-line h-full min-h-0 w-[var(--pc-left-width)] shrink-0 overflow-auto rounded-md border">
      <slot name="left" />
    </aside>
    <div class="page-container__body flex h-full w-0 min-h-0 min-w-0 flex-1 flex-col bg-transparent">
      <slot v-if="hasTopExpand" name="topExpand" />
      <div v-if="hasSearch" class="page-container__search border-line bg-surface flex shrink-0 flex-wrap items-center gap-2 border-b px-[var(--pad-sheet-x)] py-2">
        <slot name="search" />
      </div>
      <div v-if="hasMain" class="page-container__main flex h-0 min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden p-0">
        <slot name="main" />
      </div>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.page-container__left { overscroll-behavior: contain; }
.page-container__search > :deep(*) { max-width: 100%; }
@media (max-width: 640px) {
  .page-container { flex-direction: column; }
  .page-container__left {
    width: 100%;
    height: auto;
    max-height: 35%;
    flex-shrink: 1;
  }
  .page-container__body { width: 100%; height: 0; }
  .page-container__search { padding-inline: var(--gap-2); }
}
</style>
