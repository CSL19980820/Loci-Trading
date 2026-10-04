import type { InjectionKey, Ref } from 'vue'

export const dialogVisibilityKey: InjectionKey<Readonly<Ref<boolean>>> = Symbol('dialog-visibility')
