import { useMediaQuery } from '@vueuse/core'

/** 页面结构的手机断点；平板继续采用可缩放的工作台布局。 */
export const MOBILE_QUERY = '(max-width: 767px)'

export function useMobileLayout() {
  return useMediaQuery(MOBILE_QUERY)
}
