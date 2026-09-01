/**
 * 大屏的「暗色盯盘」开关。**默认关：大屏跟随用户自己选的外观，不擅自改色。**
 *
 * ── 为什么从「强制墨黑」退回「可选」 ──
 *
 * 旧版进大屏就把 `<html>` 钉成墨黑，理由是盯盘墙习惯暗色。但那是**替用户做了
 * 外观决定**：日间档的人点一下「大屏」，整个 App（含侧栏、EP 弹层）当场变黑，
 * 退出来才变回去。用户原话：「这个大屏还是会改我颜色啊」。
 *
 * `live-theme.css` 的 `--live-*` 全部派生自全局令牌，明暗两档本来就都成立，
 * 所以「跟随外观」不需要任何额外样式——旧版是主动放弃了这个能力。
 *
 * 想要暗色盯盘墙的人按顶栏那颗开关，选择**记在 localStorage**，下次进来还在。
 *
 * ── 三个必须守住的细节 ──
 *
 * 1. **钉在 `<html>` 上**：夜盘令牌定义在 `html[data-appearance='ink']` 这类元素
 *    选择器上（`style.theme.css`），写在大屏根 div 上一条都匹配不到；钉 `<html>`
 *    还能让 teleport 到 body 的 EP 弹层一起变深，不出现「深色大屏 + 亮白气泡」。
 * 2. **恢复靠重放主题 store，不靠 DOM 快照**。快照法有个隐蔽 bug：在大屏上打开
 *    「主题」改了外观，离开时会被快照原样回滚，等于大屏偷偷改回了用户的新选择。
 *    重放 `applyTheme(store 里的三个值)` 永远回到唯一真相。
 * 3. **onActivated / onDeactivated 与 onMounted / onUnmounted 都要挂**：主区路由被
 *    `PageHost.vue` 的 `<KeepAlive>` 包着，离开只触发 deactivated；只挂 unmounted
 *    就会把整站永久钉在墨黑里（这条是上一轮的真实事故）。两套钩子都幂等。
 */
import { onActivated, onDeactivated, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

import { applyTheme } from '@/shared/lib/theme'
import { useThemeStore } from '@/shared/stores/theme'

const INK = 'ink'
export const LIVE_INK_KEY = 'loci-live-ink'

function readStored(): boolean {
  try {
    return localStorage.getItem(LIVE_INK_KEY) === '1'
  } catch {
    // 隐私模式下 localStorage 会抛；盯盘偏好不是关键路径，静默回落到「跟随外观」
    return false
  }
}

function writeStored(on: boolean): void {
  try {
    localStorage.setItem(LIVE_INK_KEY, on ? '1' : '0')
  } catch {
    /* 同上：存不下就只在本次会话生效 */
  }
}

export function useBoardInk(): { inkOn: Ref<boolean>; toggleInk: () => void } {
  const theme = useThemeStore()
  const inkOn = ref(readStored())
  /** true = 此刻 `<html>` 正被大屏钉着，需要在离开时还给主题 store */
  let pinned = false
  /** 组件是否处于「在场」状态：不在场时不碰 `<html>` */
  let onBoard = false

  function pin(): void {
    if (typeof document === 'undefined' || pinned) return
    pinned = true
    const root = document.documentElement
    root.setAttribute('data-appearance', INK)
    root.setAttribute('data-theme', INK)
    root.classList.add('dark')
    root.style.colorScheme = 'dark'
  }

  /** 把 `<html>` 交还给主题 store：重放而不是回滚，见文件头第 2 条 */
  function unpin(): void {
    if (typeof document === 'undefined' || !pinned) return
    pinned = false
    applyTheme(theme.appearanceId, theme.primaryId, theme.customColor)
  }

  function sync(): void {
    if (!onBoard) return
    if (inkOn.value) pin()
    else unpin()
  }

  function enter(): void {
    onBoard = true
    sync()
  }

  function leave(): void {
    onBoard = false
    unpin()
  }

  function toggleInk(): void {
    inkOn.value = !inkOn.value
    writeStored(inkOn.value)
    sync()
  }

  /*
   * 在大屏上改外观（侧栏「主题」）= 明确的用户决定，暗色盯盘这个页面级覆盖就该让位，
   * 否则两边会互相盖，用户点了没反应。
   */
  watch(
    () => theme.appearanceId,
    () => {
      if (!inkOn.value) return
      inkOn.value = false
      writeStored(false)
      pinned = false
    },
  )

  // 注册与移除无条件对称（AGENTS §3.2）：判空放在 enter / leave 自身
  onMounted(enter)
  onActivated(enter)
  onDeactivated(leave)
  onUnmounted(leave)

  return { inkOn, toggleInk }
}
