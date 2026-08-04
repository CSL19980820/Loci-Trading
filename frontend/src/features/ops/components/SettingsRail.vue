<script setup lang="ts">
export type RailMark = 'ok' | 'idle' | 'bad'

export type SettingsRailItem = {
  name: string
  label: string
  tail?: string
  state?: RailMark
}

export type SettingsRailGroup = {
  title: string
  items: SettingsRailItem[]
}

defineProps<{
  modelValue: string
  groups: SettingsRailGroup[]
}>()

const emit = defineEmits<{
  'update:modelValue': [string]
}>()

function pick(name: string): void {
  emit('update:modelValue', name)
}

function onKeydown(event: KeyboardEvent, flat: string[]): void {
  const idx = flat.indexOf(
    (event.currentTarget as HTMLElement | null)?.dataset.name ?? '',
  )
  if (idx < 0) return
  let next = idx
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = Math.min(flat.length - 1, idx + 1)
  else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = Math.max(0, idx - 1)
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = flat.length - 1
  else return
  event.preventDefault()
  pick(flat[next]!)
  const el = document.querySelector<HTMLElement>(`[data-settings-rail="${flat[next]}"]`)
  el?.focus()
}
</script>

<template>
  <nav class="settings-rail" aria-label="设置分区">
    <div
      v-for="group in groups"
      :key="group.title"
      class="settings-rail__group"
      role="presentation"
    >
      <h3 class="settings-rail__group-title">{{ group.title }}</h3>
      <div
        role="tablist"
        :aria-label="group.title"
        class="settings-rail__list"
      >
        <el-button
          v-for="item in group.items"
          :key="item.name"
          native-type="button"
          role="tab"
          class="settings-rail__item"
          :class="{ 'is-active': modelValue === item.name }"
          :aria-selected="modelValue === item.name"
          :data-name="item.name"
          :data-settings-rail="item.name"
          @click="pick(item.name)"
          @keydown="
            onKeydown(
              $event,
              groups.flatMap((g) => g.items.map((i) => i.name)),
            )
          "
        >
          <span
            class="settings-rail__mark"
            :class="`settings-rail__mark--${item.state || 'idle'}`"
            aria-hidden="true"
          />
          <span class="settings-rail__label">{{ item.label }}</span>
          <span
            v-if="item.tail"
            class="settings-rail__tail"
            :class="{ 'is-bad': item.state === 'bad' }"
          >{{ item.tail }}</span>
        </el-button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.settings-rail {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 0.55rem 0 0.65rem;
  background: color-mix(in srgb, var(--paper) 70%, var(--sheet));
}

.settings-rail__group {
  margin-bottom: 0.35rem;
}

.settings-rail__group-title {
  margin: 0;
  padding: 0.15rem 0.75rem 0.25rem;
  font-size: 0.68rem;
  font-weight: 650;
  letter-spacing: 0.14em;
  color: var(--mist);
}

.settings-rail__list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.settings-rail__item {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  width: 100%;
  margin: 0;
  padding: 0.4rem 0.75rem;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--ink);
  font: 450 0.88rem/1.25 var(--font);
  text-align: left;
  cursor: pointer;
}

.settings-rail__item.el-button {
  height: auto;
  margin: 0;
  border-radius: 0;
  justify-content: flex-start;
  --el-button-text-color: var(--ink);
  --el-button-hover-text-color: var(--ink);
}

.settings-rail__item:hover {
  background: color-mix(in srgb, var(--panel-2) 80%, transparent);
}

.settings-rail__item.is-active {
  background: var(--seal-soft);
  font-weight: 650;
}

.settings-rail__mark {
  width: 0.45rem;
  height: 0.45rem;
  flex-shrink: 0;
  border-radius: 1px;
  border: 1px solid var(--rule);
  background: transparent;
}

.settings-rail__mark--ok {
  border: none;
  background: var(--lake);
}

.settings-rail__mark--bad {
  border: none;
  background: var(--seal-ink);
}

.settings-rail__mark--idle {
  background: transparent;
}

.settings-rail__label {
  flex: 1 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.settings-rail__tail {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 0.68rem;
  color: var(--mist);
  white-space: nowrap;
}

.settings-rail__tail.is-bad {
  color: var(--seal-ink);
}
</style>
