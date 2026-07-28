import { computed, ref, watch, type Ref } from 'vue'

/** Client-side slice pagination for in-memory lists. */
export function useClientPagination<T>(source: Ref<readonly T[]> | (() => readonly T[]), pageSize = 20) {
  const currentPage = ref(1)
  const size = pageSize

  const list = computed(() => (typeof source === 'function' ? source() : source.value))

  const total = computed(() => list.value.length)

  const paginated = computed(() => {
    const start = (currentPage.value - 1) * size
    return list.value.slice(start, start + size)
  })

  watch(total, (n) => {
    const maxPage = Math.max(1, Math.ceil(n / size))
    if (currentPage.value > maxPage) currentPage.value = maxPage
  })

  function reset(): void {
    currentPage.value = 1
  }

  return {
    currentPage,
    pageSize: size,
    total,
    paginated,
    reset,
  }
}
