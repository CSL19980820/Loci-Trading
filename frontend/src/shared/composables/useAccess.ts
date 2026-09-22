import { inject, ref, type InjectionKey, type Ref } from 'vue'

/** Presentation policy only. The server independently rejects every visitor write. */
export const VISITOR_MODE: InjectionKey<Readonly<Ref<boolean>>> = Symbol('loci.visitor-mode')
export type ControlAccess = 'read' | 'write'
export function useVisitorMode(): Readonly<Ref<boolean>> {
  return inject(VISITOR_MODE, ref(false))
}
