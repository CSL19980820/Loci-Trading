import { nextTick, onBeforeUnmount, watch } from 'vue'

/** Observe controlled state as well as user gestures; ignore stale transition callbacks. */
export function usePanelLifecycle(
  open: () => boolean | undefined,
  notify: (event: 'opened' | 'closed' | 'close') => void,
) {
  let generation = 0
  onBeforeUnmount(() => { generation++ })
  watch(() => Boolean(open()), async (value, previous) => {
    const run = ++generation
    if (!value && !previous) return
    if (!value) notify('close')
    await nextTick()
    if (run === generation) notify(value ? 'opened' : 'closed')
  }, { immediate: true, flush: 'post' })
}
