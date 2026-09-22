import type { InjectionKey } from 'vue'
export const actionMenuKey: InjectionKey<(command: unknown) => void> = Symbol('action-menu')
