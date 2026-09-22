<script setup lang="ts">
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Check, Moon, Palette, Sun } from '@lucide/vue'
import { computed } from 'vue'

import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Switch } from '@/shared/components/ui/switch'
import { useThemeStore } from '@/shared/stores/theme'
import { contrastRatio, type AppearanceOption } from '@/shared/lib/theme'

/**
 * 主题与外观（Raycast / Linear 设置页一路）：
 *   外观 —— 四张迷你界面预览卡（真实配色画的缩略图），选中带主色描边 + 角标勾。
 *   强调色 —— 一排 32px 圆色块，选中项放大并带白环；自定义取色盘与预设排在同一行。
 *   预览条 —— 当前外观 × 主色下的按钮、徽标、开关，一眼看到效果。
 */
defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
const store = useThemeStore()
const appearanceName = computed(() => store.appearances.find((item) => item.id === store.appearanceId)?.label)
const primaryName = computed(() =>
  store.isCustom ? '自定义' : store.primaries.find((item) => item.id === store.primaryId)?.label,
)
const appearanceHints: Record<string, string> = {
  day: '明亮清晰',
  paper: '柔和暖色',
  night: '深蓝低光',
  ink: '纯黑高对比',
}
const corrected = computed(() => contrastRatio(store.customColor, store.customScale['--seal']) > 1.35)

function previewStyle(item: AppearanceOption): Record<string, string> {
  return {
    '--preview-canvas': item.preview.canvas,
    '--preview-surface': item.preview.surface,
    '--preview-border': item.preview.border,
    '--preview-text': item.preview.text,
    '--preview-accent': store.isCustom ? store.customScale['--seal'] : (store.primaries.find((p) => p.id === store.primaryId)?.color ?? '#396ed6'),
  }
}

function updateCustom(value: string | null): void {
  if (value) store.setCustomPrimary(value)
}

/** 取色盘只在 `change` 时落地——拖拽过程中 `input` 会连续触发，每次都重算 OKLCH 色阶并写 CSS 变量 */
function onPicked(event: Event): void {
  updateCustom((event.target as HTMLInputElement | null)?.value ?? null)
}
</script>

<template>
  <Dialog :open="modelValue" @update:open="emit('update:modelValue', $event)">
    <DialogContent class="theme-dialog gap-0 p-0 sm:max-w-[720px]">
      <DialogHeader class="theme-dialog__head">
        <span class="theme-dialog__icon"><Palette aria-hidden="true" /></span>
        <div class="theme-dialog__titles">
          <DialogTitle>主题与外观</DialogTitle>
          <DialogDescription>更改即时生效并自动保存；涨跌颜色不受强调色影响。</DialogDescription>
        </div>
      </DialogHeader>

      <div class="theme-settings">
        <section class="theme-section" aria-labelledby="theme-appearance-heading">
          <div class="theme-section__heading">
            <h3 id="theme-appearance-heading">界面外观</h3>
            <span>{{ appearanceName }}</span>
          </div>
          <ToggleGroup type="single" :model-value="store.appearanceId" class="appearance-grid w-full" aria-label="界面外观" @update:model-value="value => typeof value === 'string' && value && store.setAppearance(value)">
            <ToggleGroupItem
              v-for="item in store.appearances"
              :key="item.id"
              type="button"
              class="appearance-card"
              :class="{ 'is-selected': store.appearanceId === item.id }"
              :aria-label="item.label"
              :aria-pressed="store.appearanceId === item.id"
              :value="item.id"
            >
              <span class="theme-preview" :style="previewStyle(item)" aria-hidden="true">
                <span class="theme-preview__nav">
                  <i class="theme-preview__brand" /><i /><i class="is-active" /><i /><i />
                </span>
                <span class="theme-preview__content">
                  <span class="theme-preview__toolbar"><i /><i class="is-accent" /></span>
                  <span class="theme-preview__metrics"><i /><i /><i /></span>
                  <span class="theme-preview__table"><i /><i /><i /><i /></span>
                </span>
              </span>
              <span class="appearance-card__caption">
                <component :is="item.mode === 'dark' ? Moon : Sun" class="appearance-card__mode" aria-hidden="true" />
                <span class="appearance-card__text">
                  <strong>{{ item.label }}</strong>
                  <small>{{ appearanceHints[item.id] || item.hint }}</small>
                </span>
              </span>
              <span v-if="store.appearanceId === item.id" class="selection-check" aria-hidden="true"><Check /></span>
            </ToggleGroupItem>
          </ToggleGroup>
        </section>

        <section class="theme-section" aria-labelledby="theme-accent-heading">
          <div class="theme-section__heading">
            <h3 id="theme-accent-heading">强调色</h3>
            <span>{{ primaryName }}</span>
          </div>
          <div class="accent-row">
            <ToggleGroup type="single" :model-value="store.primaryId" class="accent-grid" aria-label="强调色" @update:model-value="value => typeof value === 'string' && value && store.setPrimary(value)">
              <ToggleGroupItem
                v-for="item in store.primaries"
                :key="item.id"
                type="button"
                class="accent-choice"
                :class="{ 'is-selected': store.primaryId === item.id }"
                :aria-label="item.label"
                :aria-pressed="store.primaryId === item.id"
                :title="item.label"
                :value="item.id"
              >
                <span class="accent-choice__color" :style="{ background: item.color }" aria-hidden="true">
                  <Check v-if="store.primaryId === item.id" class="accent-choice__check" />
                </span>
              </ToggleGroupItem>
            </ToggleGroup>
            <span class="accent-row__divider" aria-hidden="true" />
            <div class="custom-accent">
              <Label class="custom-accent__picker-wrap" :class="{ 'is-selected': store.isCustom }" :title="`自定义 ${store.customColor.toUpperCase()}`">
                <Input
                  type="color"
                  class="custom-accent__picker"
                  :model-value="store.customColor"
                  aria-label="自定义强调色"
                  @change="onPicked"
                />
                <span class="custom-accent__swatch" :style="{ background: store.isCustom ? store.customScale['--seal'] : 'conic-gradient(from 90deg, #cc323e, #d79700, #298646, #007ca8, #396ed6, #854ece, #cc323e)' }" aria-hidden="true">
                  <Check v-if="store.isCustom" class="accent-choice__check" />
                </span>
              </Label>
              <Button access="read" variant="ghost"
                v-for="preset in store.presets"
                :key="preset"
                type="button"
                class="custom-accent__preset"
                :style="{ background: preset }"
                :aria-label="`使用预设色 ${preset}`"
                @click="updateCustom(preset)"
              />
            </div>
          </div>
          <div class="custom-accent__meta">
            <span class="custom-accent__value">{{ store.isCustom ? store.customColor.toUpperCase() : '内置色板' }}</span>
            <span class="custom-accent__hint" :class="{ 'is-corrected': store.isCustom && corrected }">
              {{ store.isCustom && corrected ? '已自动调整对比度，确保文字清晰' : '任意颜色都会按对比度自动校正' }}
            </span>
          </div>
        </section>

        <section class="control-preview" aria-label="控件效果预览">
          <div class="control-preview__caption">
            <strong>效果预览</strong>
            <span>{{ appearanceName }} · {{ primaryName }}</span>
          </div>
          <div class="control-preview__items">
            <Button access="read" type="button" size="sm">主要操作</Button>
            <Button access="read" type="button" variant="outline" size="sm">次要操作</Button>
            <Badge variant="soft">已选中</Badge>
            <Badge variant="up">+2.41%</Badge>
            <Badge variant="down">-1.08%</Badge>
            <Switch :model-value="true" aria-label="示例开关" />
          </div>
        </section>
      </div>

      <DialogFooter class="theme-dialog__footer">
        <span class="theme-save-status" role="status"><Check aria-hidden="true" />更改即时生效，已自动保存</span>
        <Button access="read" type="button" @click="emit('update:modelValue', false)">完成</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped src="./ThemeDialog.css" />
