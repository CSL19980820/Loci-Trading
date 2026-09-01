import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  APPEARANCE_OPTIONS,
  CUSTOM_PRESETS,
  CUSTOM_PRIMARY_ID,
  DEFAULT_APPEARANCE,
  DEFAULT_PRIMARY,
  PRIMARY_OPTIONS,
  applyTheme,
  appearanceMode,
  derivePrimaryScale,
  getStoredAppearance,
  getStoredCustomColor,
  getStoredPrimary,
  normalizeCustomColor,
  type AppearanceOption,
  type PrimaryOption,
  type PrimaryScale,
} from '@/shared/lib/theme'

export const useThemeStore = defineStore('theme', () => {
  const appearanceId = ref(getStoredAppearance() || DEFAULT_APPEARANCE)
  const primaryId = ref(getStoredPrimary() || DEFAULT_PRIMARY)
  /** 用户自选主色的原始 hex（未经对比度校正，回填给取色器） */
  const customColor = ref(getStoredCustomColor())

  const appearances = computed((): AppearanceOption[] => APPEARANCE_OPTIONS)
  const primaries = computed((): PrimaryOption[] => PRIMARY_OPTIONS)
  const presets = computed((): string[] => CUSTOM_PRESETS)
  const isCustom = computed((): boolean => primaryId.value === CUSTOM_PRIMARY_ID)

  /** 校正后的实际色阶：给弹窗做实时预览与「已自动校正」提示用 */
  const customScale = computed(
    (): PrimaryScale => derivePrimaryScale(customColor.value, appearanceMode(appearanceId.value)),
  )

  function setAppearance(id: string): void {
    if (!APPEARANCE_OPTIONS.some((o) => o.id === id)) return
    appearanceId.value = id
    // 自定义主色的明暗两档亮度不同，换外观必须重算，否则深色档上主色发闷
    applyTheme(appearanceId.value, primaryId.value, customColor.value)
  }

  function setPrimary(id: string): void {
    if (id !== CUSTOM_PRIMARY_ID && !PRIMARY_OPTIONS.some((o) => o.id === id)) return
    primaryId.value = id
    applyTheme(appearanceId.value, primaryId.value, customColor.value)
  }

  /** 选定自定义主色：顺带把 primaryId 切到 'custom'，不用用户再点一下 */
  function setCustomPrimary(hex: string): void {
    customColor.value = normalizeCustomColor(hex)
    primaryId.value = CUSTOM_PRIMARY_ID
    applyTheme(appearanceId.value, primaryId.value, customColor.value)
  }

  return {
    appearanceId,
    primaryId,
    customColor,
    appearances,
    primaries,
    presets,
    isCustom,
    customScale,
    setAppearance,
    setPrimary,
    setCustomPrimary,
  }
})
