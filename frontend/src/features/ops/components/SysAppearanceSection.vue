<script setup lang="ts">
import { ref } from 'vue'

import { getDesktopPrefs, saveDesktopPrefs } from '@/shared/api/quant'
import { useThemeStore } from '@/shared/stores/theme'
import { useOpsFeedback } from '../composables/useOpsFeedback'

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
  <el-form class="sys-form" label-position="left" label-width="5.5rem" @submit.prevent>
    <el-row :gutter="12">
      <el-col :xs="24" :xl="12">
        <el-form-item label="主题">
          <div class="swatch-row">
            <el-button
              v-for="item in theme.appearances"
              :key="item.id"
              class="swatch"
              :class="{ 'swatch--on': theme.appearanceId === item.id }"
              :style="{ '--sw': item.swatch }"
              @click="setAppearance(item.id)"
            >
              <span class="swatch__chip" />
              {{ item.label }}
            </el-button>
          </div>
        </el-form-item>
      </el-col>
      <el-col :xs="24" :xl="12">
        <el-form-item label="主色">
          <div class="swatch-row">
            <el-button
              v-for="item in theme.primaries"
              :key="item.id"
              class="swatch"
              :class="{ 'swatch--on': theme.primaryId === item.id }"
              :style="{ '--sw': item.color }"
              @click="setPrimary(item.id)"
            >
              <span class="swatch__chip" />
              {{ item.label }}
            </el-button>
          </div>
        </el-form-item>
      </el-col>
      <el-col :xs="24" :md="12">
        <el-form-item label="窗口">
          <div class="pref-row">
            <span>最小化到托盘</span>
            <el-switch
              :model-value="minimizeToTray"
              :disabled="busy"
              @change="onMinimizeToTrayChange"
            />
            <el-tooltip content="关闭则缩回任务栏" placement="top">
              <span class="hint-q" tabindex="0">?</span>
            </el-tooltip>
          </div>
        </el-form-item>
      </el-col>
    </el-row>
  </el-form>
</template>

<style scoped>
.swatch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.swatch.el-button {
  --el-button-bg-color: transparent;
  --el-button-border-color: var(--rule);
  --el-button-text-color: var(--ink);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: var(--seal);
  --el-button-hover-text-color: var(--ink);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: var(--seal);
  height: auto;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
  font-weight: 500;
}

.swatch--on.el-button {
  --el-button-border-color: var(--seal);
  --el-button-hover-border-color: var(--seal);
}

.swatch__chip {
  width: 0.8rem;
  height: 0.8rem;
  margin-right: 0.35rem;
  border-radius: 2px;
  background: var(--sw);
  border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
}

.pref-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.86rem;
}

.hint-q {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: 1px solid var(--rule);
  border-radius: 50%;
  font-size: 0.68rem;
  color: var(--mist);
  cursor: help;
}

.sys-form :deep(.el-form-item) {
  margin-bottom: 0.45rem;
}
</style>
