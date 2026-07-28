import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  APPEARANCE_OPTIONS,
  DEFAULT_APPEARANCE,
  DEFAULT_PRIMARY,
  PRIMARY_OPTIONS,
  applyTheme,
  getStoredAppearance,
  getStoredPrimary,
  type AppearanceOption,
  type PrimaryOption,
} from '@/shared/lib/theme'

export const useThemeStore = defineStore('theme', () => {
  const appearanceId = ref(getStoredAppearance() || DEFAULT_APPEARANCE)
  const primaryId = ref(getStoredPrimary() || DEFAULT_PRIMARY)

  const appearances = computed((): AppearanceOption[] => APPEARANCE_OPTIONS)
  const primaries = computed((): PrimaryOption[] => PRIMARY_OPTIONS)

  function setAppearance(id: string): void {
    if (!APPEARANCE_OPTIONS.some((o) => o.id === id)) return
    appearanceId.value = id
    applyTheme(appearanceId.value, primaryId.value)
  }

  function setPrimary(id: string): void {
    if (!PRIMARY_OPTIONS.some((o) => o.id === id)) return
    primaryId.value = id
    applyTheme(appearanceId.value, primaryId.value)
  }

  return {
    appearanceId,
    primaryId,
    appearances,
    primaries,
    setAppearance,
    setPrimary,
  }
})
