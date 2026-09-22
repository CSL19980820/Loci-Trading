<script setup lang="ts">
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import { Label } from '@/shared/components/ui/label'
import { Check } from '@lucide/vue'
import { ref } from 'vue'

import { getDesktopPrefs, saveDesktopPrefs } from '@/shared/api/quant'
import { Switch } from '@/shared/components/ui/switch'
import { useThemeStore } from '@/shared/stores/theme'
import { useOpsFeedback } from '../composables/useOpsFeedback'

/** 外观与窗口一节：主题 / 主色 两排色板（Raycast Appearance 式）+ 托盘开关一行。 */
const emit = defineEmits<{ changed: [] }>()

const { busy, guard } = useOpsFeedback()
const theme = useThemeStore()
const minimizeToTray = ref(true)

async function load(): Promise<void> {
  const prefs = await getDesktopPrefs()
  minimizeToTray.value = prefs.minimize_to_tray !== false
}

async function onMinimizeToTrayChange(value: string | number | boolean): Promise<void> {
  const enabled = Boolean(value)
  minimizeToTray.value = enabled
  const saved = await guard(() => saveDesktopPrefs({ minimize_to_tray: enabled }))
  if (!saved) {
    minimizeToTray.value = !enabled
    return
  }
  minimizeToTray.value = saved.minimize_to_tray
  emit('changed')
}

function setAppearance(id: string): void {
  theme.setAppearance(id)
  emit('changed')
}

function setPrimary(id: string): void {
  theme.setPrimary(id)
  emit('changed')
}

defineExpose({ load })
</script>

<template>
  <form class="sys-rows" @submit.prevent>
    <div class="settings-row settings-row--stack">
      <div class="settings-row__lead">
        <span class="settings-row__label">主题</span>
        
      </div>
      <ToggleGroup type="single" :model-value="theme.appearanceId" class="settings-row__control swatch-row flex-wrap" aria-label="主题" @update:model-value="value => typeof value === 'string' && value && setAppearance(value)">
        <ToggleGroupItem
          v-for="item in theme.appearances"
          :key="item.id"
          type="button"
          class="swatch"
          :class="{ 'is-on': theme.appearanceId === item.id }"
          :style="{ '--sw': item.swatch }"
          :aria-checked="theme.appearanceId === item.id"
          :value="item.id"
        >
          <span class="swatch__tile" aria-hidden="true">
            <Check v-if="theme.appearanceId === item.id" class="swatch__check" />
          </span>
          <span class="swatch__label">{{ item.label }}</span>
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
    <div class="settings-row settings-row--stack">
      <div class="settings-row__lead">
        <span class="settings-row__label">主色</span>
        
      </div>
      <ToggleGroup type="single" :model-value="theme.primaryId" class="settings-row__control swatch-row flex-wrap" aria-label="主色" @update:model-value="value => typeof value === 'string' && value && setPrimary(value)">
        <ToggleGroupItem
          v-for="item in theme.primaries"
          :key="item.id"
          type="button"
          class="swatch swatch--dot"
          :class="{ 'is-on': theme.primaryId === item.id }"
          :style="{ '--sw': item.color }"
          :aria-checked="theme.primaryId === item.id"
          :value="item.id"
        >
          <span class="swatch__tile" aria-hidden="true">
            <Check v-if="theme.primaryId === item.id" class="swatch__check" />
          </span>
          <span class="swatch__label">{{ item.label }}</span>
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
    <div class="settings-row">
      <div class="settings-row__lead">
        <Label class="settings-row__label" for="sys-tray-switch">最小化到托盘</Label>
        <p class="settings-row__desc">关闭窗口时缩到系统托盘继续跑定时任务；关掉则缩回任务栏。</p>
      </div>
      <div class="settings-row__control">
        <Switch
          id="sys-tray-switch"
          :model-value="minimizeToTray"
          aria-label="最小化到托盘"
          :disabled="busy"
          @update:model-value="onMinimizeToTrayChange"
        />
      </div>
    </div>
  </form>
</template>

<style scoped>
.sys-rows {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
}

.swatch-row {
  gap: var(--gap-2);
}

.swatch-row :deep(.swatch) {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  height: var(--ctl-h);
  padding: 0 var(--gap-3) 0 6px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 500;
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.swatch-row :deep(.swatch:hover) {
  border-color: var(--border-default);
  background: var(--surface-hover);
  color: var(--text-primary);
}

.swatch-row :deep(.swatch.is-on) {
  border-color: var(--seal-border);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
}

.swatch-row :deep(.swatch:focus-visible) {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.swatch__tile {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 1px solid color-mix(in oklab, var(--text-primary) 14%, transparent);
  border-radius: var(--radius-sm);
  background: var(--sw);
}

.swatch-row :deep(.swatch--dot) .swatch__tile {
  border-radius: 50%;
}

.swatch__check {
  width: 12px;
  height: 12px;
  color: #fff;
  stroke-width: 3;
  filter: drop-shadow(0 1px 1px rgb(0 0 0 / 0.35));
}

@media (max-width: 640px) {
  .swatch-row :deep(.swatch) {
    min-height: 40px;
  }
}
</style>
