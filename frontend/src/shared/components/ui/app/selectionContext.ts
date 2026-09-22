import type { ComputedRef, InjectionKey } from 'vue'

export const checkboxContextKey: InjectionKey<{
  value: ComputedRef<unknown[]>; disabled: ComputedRef<boolean>;
  toggle: (value: unknown, checked: boolean) => void
}> = Symbol('checkbox-choices')
export const radioContextKey: InjectionKey<{
  value: ComputedRef<unknown>; disabled: ComputedRef<boolean>
}> = Symbol('radio-choices')
