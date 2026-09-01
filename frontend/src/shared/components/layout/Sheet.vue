<script setup lang="ts">
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
  }>(),
  {
    mutedChip: false,
    quiet: false,
    plain: false,
    padded: false,
    margin: false,
  },
)
</script>

<template>
  <section
    class="sheet"
    :class="{ 'sheet-quiet': quiet, 'sheet-plain': plain, mb: margin }"
  >
    <header
      v-if="title || $slots.header || $slots.actions || $slots.meta"
      class="sheet-bar"
      :class="{ 'quiet-bar': quiet }"
    >
      <slot name="header">
        <h2>
          {{ title }}
          <span v-if="chip" class="chip" :class="{ 'muted-chip': mutedChip }">{{ chip }}</span>
        </h2>
      </slot>
      <div v-if="$slots.meta || $slots.actions" class="sheet-bar__right">
        <span v-if="$slots.meta" class="sheet-meta"><slot name="meta" /></span>
        <div v-if="$slots.actions" class="sheet-actions">
          <slot name="actions" />
        </div>
      </div>
    </header>
    <div class="sheet-slot" :class="{ 'sheet-body': padded }">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.sheet-bar__right {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.sheet-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
}

.sheet-slot {
  min-width: 0;
}
</style>
