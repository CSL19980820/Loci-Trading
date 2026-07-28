<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    chip?: string | number
    mutedChip?: boolean
    quiet?: boolean
    padded?: boolean
    margin?: boolean
  }>(),
  {
    mutedChip: false,
    quiet: false,
    padded: false,
    margin: false,
  },
)
</script>

<template>
  <section class="sheet" :class="{ 'sheet-quiet': quiet, mb: margin }">
    <header v-if="title || $slots.header || $slots.actions" class="sheet-bar">
      <slot name="header">
        <h2>
          {{ title }}
          <span v-if="chip" class="chip" :class="{ 'muted-chip': mutedChip }">{{ chip }}</span>
        </h2>
      </slot>
      <div v-if="$slots.actions" class="sheet-actions">
        <slot name="actions" />
      </div>
    </header>
    <div :class="padded ? 'sheet-body' : undefined">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.sheet-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}
</style>
