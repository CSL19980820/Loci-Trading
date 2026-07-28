import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'
import { CapabilityUnavailableError } from '@/shared/api/quant'

export type OpsFeedback = {
  busy: Ref<boolean>
  notice: Ref<string>
  errorText: Ref<string>
  guard: <T>(task: () => Promise<T>, done?: string) => Promise<T | null>
}

const OPS_FEEDBACK_KEY: InjectionKey<OpsFeedback> = Symbol('ops-feedback')

export function createOpsFeedback(): OpsFeedback {
  const busy = ref(false)
  const notice = ref('')
  const errorText = ref('')

  async function guard<T>(task: () => Promise<T>, done?: string): Promise<T | null> {
    busy.value = true
    errorText.value = ''
    notice.value = ''
    try {
      const result = await task()
      if (done) notice.value = done
      return result
    } catch (caught: unknown) {
      errorText.value =
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

  return { busy, notice, errorText, guard }
}

export function provideOpsFeedback(feedback: OpsFeedback = createOpsFeedback()): OpsFeedback {
  provide(OPS_FEEDBACK_KEY, feedback)
  return feedback
}

export function useOpsFeedback(): OpsFeedback {
  const feedback = inject(OPS_FEEDBACK_KEY)
  if (!feedback) throw new Error('useOpsFeedback() requires provideOpsFeedback() in ancestor')
  return feedback
}
