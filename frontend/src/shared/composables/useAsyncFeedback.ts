import { ref } from 'vue'

import { CapabilityUnavailableError } from '@/shared/api/quant'

/** Local busy / error / notice guard for feature pages (no provide/inject). */
export function useAsyncFeedback() {
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')

  async function run<T>(task: () => Promise<T>, done?: string): Promise<T | null> {
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await task()
      if (done) notice.value = done
      return result
    } catch (caught: unknown) {
      error.value =
        caught instanceof CapabilityUnavailableError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : '请求失败'
      return null
    } finally {
      busy.value = false
    }
  }

  function clearError(): void {
    error.value = ''
  }

  function clearNotice(): void {
    notice.value = ''
  }

  return { busy, error, notice, run, clearError, clearNotice }
}
