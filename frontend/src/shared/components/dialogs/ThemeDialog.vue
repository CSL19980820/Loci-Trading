<script setup lang="ts">
import { useThemeStore } from '@/shared/stores/theme'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
const store = useThemeStore()
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="主题"
    width="28rem"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <section class="theme-block">
      <h3>外观</h3>
      <div class="swatch-row">
        <button
          v-for="item in store.appearances"
          :key="item.id"
          type="button"
          class="swatch"
          :class="{ 'swatch--on': store.appearanceId === item.id }"
          :style="{ '--sw': item.swatch }"
          @click="store.setAppearance(item.id)"
        >
          <span class="swatch__chip" />
          {{ item.label }}
        </button>
      </div>
    </section>
    <section class="theme-block">
      <h3>主色</h3>
      <div class="swatch-row">
        <button
          v-for="item in store.primaries"
          :key="item.id"
          type="button"
          class="swatch"
          :class="{ 'swatch--on': store.primaryId === item.id }"
          :style="{ '--sw': item.color }"
          @click="store.setPrimary(item.id)"
        >
          <span class="swatch__chip" />
          {{ item.label }}
        </button>
      </div>
    </section>
  </el-dialog>
</template>

<style scoped>
.theme-block + .theme-block {
  margin-top: 1.1rem;
}
.theme-block h3 {
  margin: 0 0 0.55rem;
  font-size: 0.82rem;
  color: var(--mist);
  font-weight: 600;
}
.swatch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.swatch {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid var(--rule);
  background: var(--sheet);
  color: var(--ink);
  border-radius: var(--radius);
  padding: 0.35rem 0.55rem;
  font: inherit;
  font-size: 0.82rem;
  cursor: pointer;
}
.swatch--on {
  border-color: var(--seal);
  box-shadow: 0 0 0 1px var(--seal);
}
.swatch__chip {
  width: 0.85rem;
  height: 0.85rem;
  border-radius: 999px;
  background: var(--sw);
  border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
}
</style>
