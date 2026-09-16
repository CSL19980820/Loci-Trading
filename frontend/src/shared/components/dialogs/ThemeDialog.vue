<script setup lang="ts">
import { computed } from 'vue'
import { Check } from '@element-plus/icons-vue'

import { useThemeStore } from '@/shared/stores/theme'
import { contrastRatio, type AppearanceOption } from '@/shared/lib/theme'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
const store = useThemeStore()
const appearanceName = computed(() => store.appearances.find((item) => item.id === store.appearanceId)?.label)
const primaryName = computed(() => store.isCustom ? '自定义' : store.primaries.find((item) => item.id === store.primaryId)?.label)
const appearanceHints: Record<string, string> = {
  day: '明亮清晰', paper: '柔和暖色', night: '深蓝低光', ink: '纯黑高对比',
}
const corrected = computed(() => contrastRatio(store.customColor, store.customScale['--seal']) > 1.35)

function previewStyle(item: AppearanceOption): Record<string, string> {
  return {
    '--preview-canvas': item.preview.canvas, '--preview-surface': item.preview.surface,
    '--preview-border': item.preview.border, '--preview-text': item.preview.text,
  }
}

function updateCustom(value: string | null): void {
  if (value) store.setCustomPrimary(value)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="主题与外观"
    width="min(720px, calc(100vw - 32px))"
    class="theme-dialog"
    align-center
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="theme-settings">
      <section class="theme-section" aria-labelledby="theme-appearance-heading">
        <div class="theme-section__heading">
          <h3 id="theme-appearance-heading">界面外观</h3>
          <span>选择适合当前光线的工作台</span>
        </div>
        <div class="appearance-grid" role="group" aria-label="界面外观">
          <el-button
            v-for="item in store.appearances"
            :key="item.id"
            class="appearance-card"
            :class="{ 'is-selected': store.appearanceId === item.id }"
            :aria-label="item.label"
            :aria-pressed="store.appearanceId === item.id"
            @click="store.setAppearance(item.id)"
          >
            <span class="theme-preview" :style="previewStyle(item)" aria-hidden="true">
              <span class="theme-preview__nav"><i /><i /><i /><i /></span>
              <span class="theme-preview__content">
                <span class="theme-preview__toolbar"><i /><i /></span>
                <span class="theme-preview__metrics"><i /><i /></span>
                <span class="theme-preview__table"><i /><i /><i /></span>
              </span>
            </span>
            <span class="appearance-card__caption">
              <span><strong>{{ item.label }}</strong><small>{{ appearanceHints[item.id] || item.hint }}</small></span>
              <el-icon v-if="store.appearanceId === item.id" class="selection-check"><Check /></el-icon>
            </span>
          </el-button>
        </div>
      </section>

      <section class="theme-section" aria-labelledby="theme-accent-heading">
        <div class="theme-section__heading">
          <h3 id="theme-accent-heading">强调色</h3>
          <span>用于操作与选中状态，涨跌颜色保持不变</span>
        </div>
        <div class="accent-grid" role="group" aria-label="强调色">
          <el-button
            v-for="item in store.primaries"
            :key="item.id"
            class="accent-choice"
            :class="{ 'is-selected': store.primaryId === item.id }"
            :aria-label="item.label"
            :aria-pressed="store.primaryId === item.id"
            @click="store.setPrimary(item.id)"
          >
            <span class="accent-choice__color" :style="{ background: item.color }" aria-hidden="true" />
            <span>{{ item.label }}</span>
            <span class="accent-choice__indicator" aria-hidden="true"><el-icon v-if="store.primaryId === item.id"><Check /></el-icon></span>
          </el-button>
        </div>
        <div class="custom-accent">
          <span class="custom-accent__label">自定义颜色</span>
          <el-color-picker
            :model-value="store.customColor"
            :predefine="store.presets"
            aria-label="自定义强调色"
            @change="updateCustom"
          />
          <span class="custom-accent__value">{{ store.customColor.toUpperCase() }}</span>
          <span class="custom-accent__hint" :class="{ 'is-corrected': store.isCustom && corrected }">
            {{ store.isCustom && corrected ? '已自动调整对比度，确保文字清晰' : '选择后立即应用' }}
          </span>
        </div>
      </section>

      <section class="control-preview" aria-label="控件效果预览">
        <div class="control-preview__caption"><strong>效果预览</strong><span>{{ appearanceName }} · {{ primaryName }}</span></div>
        <div class="control-preview__items">
          <el-button type="primary" size="small">主要操作</el-button>
          <el-button size="small">次要操作</el-button>
          <el-button link type="primary" size="small">文字链接</el-button>
          <el-tag effect="light" size="small">已选中</el-tag>
        </div>
      </section>
    </div>
    <template #footer>
      <span class="theme-save-status is-leading" role="status"><el-icon><Check /></el-icon>更改即时生效，已自动保存</span>
      <el-button type="primary" @click="emit('update:modelValue', false)">完成</el-button>
    </template>
  </el-dialog>
</template>

<style scoped src="./ThemeDialog.css" />
