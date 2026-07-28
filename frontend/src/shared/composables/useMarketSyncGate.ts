import { computed, ref } from 'vue'

/** 跨页面：行情补数是否进行中（退出前提醒）。 */
const syncing = ref(false)
const syncMessage = ref('')
const syncPercent = ref(0)

export function useMarketSyncGate() {
  function setSyncing(next: boolean, message = '', percent = 0): void {
    syncing.value = next
    syncMessage.value = message
    syncPercent.value = percent
  }

  const busyLabel = computed(() => {
    if (!syncing.value) return ''
    const pct = syncPercent.value ? ` ${Math.round(syncPercent.value)}%` : ''
    return `${syncMessage.value || '正在补行情'}${pct}`
  })

  return { syncing, syncMessage, syncPercent, busyLabel, setSyncing }
}
