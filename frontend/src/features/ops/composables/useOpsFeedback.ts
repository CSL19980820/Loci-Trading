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
  let pending = 0

  async function guard<T>(task: () => Promise<T>, done?: string): Promise<T | null> {
    pending += 1
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
      pending -= 1
      busy.value = pending > 0
    }
  }

  return { busy, notice, errorText, guard }
}

export function provideOpsFeedback(feedback: OpsFeedback = createOpsFeedback()): OpsFeedback {
  provide(OPS_FEEDBACK_KEY, feedback)
  return feedback
}

export function useOpsFeedback(): OpsFeedback {
  // 旧版工坊页的部分子树没有祖先 provider；默认实例避免 Vue inject 警告，
  // 有 provider 时仍保持页面级共享反馈状态。
  return inject(OPS_FEEDBACK_KEY, createOpsFeedback, true)
}
