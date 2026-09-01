import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getAuthMe,
  getAuthSession,
  getNotifications,
  logout as apiLogout,
  markNotificationsRead,
  patchProfile as apiPatchProfile,
} from '@/shared/api/auth'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  AnnouncementItem,
  NotificationItem,
  UserProfile,
  UserQuota,
} from '@/shared/types/auth'

export const useUserStore = defineStore('user', () => {
  const user = ref<UserProfile | null>(null)
  const quota = ref<UserQuota | null>(null)
  const unread = ref<number>(0)
  const notifications = ref<NotificationItem[]>([])
  const announcements = ref<AnnouncementItem[]>([])
  const loading = ref<boolean>(false)
  const initialized = ref<boolean>(false)
  const lastError = ref<string>('')
  /**
   * 后端是否答得上话。`authenticated=false` 有两种完全不同的成因——「没登录」
   * 与「服务没起来」——路由守卫必须分得开：前者去 /login，后者去
   * /auth-unavailable。合并成一个布尔会让本机服务挂掉时把人踢去登录页，
   * 而登录页同样打不通接口，于是死循环。
   */
  const available = ref<boolean>(true)

  const authenticated = computed<boolean>(() => user.value !== null)
  const isAdmin = computed<boolean>(() => user.value?.role === 'admin')
  const mustChangePassword = computed<boolean>(() => Boolean(user.value?.must_change_password))

  /**
   * 同一次导航里可能有多个消费者同时要会话（守卫 + 组件 onMounted）。
   * 不去重就是每次导航打 N 个 /auth/session。
   */
  let inflight: Promise<boolean> | null = null

  /** 上一次 `/auth/session` 落地的时刻（epoch ms）。0 = 从没拉过。 */
  const loadedAt = ref<number>(0)

  /** 缓存新鲜期。超过它才允许后台补一次，导航链路本身永远不为此等待。 */
  const SESSION_STALE_MS = 60_000

  /**
   * 加载轻量会话（/api/auth/session）。**会真的发请求**，只有 inflight 去重。
   * 冷启动 / 登录登出这类「必须拿到最新真相」的场合才用它；
   * 每次导航都调它就是把导航钉死在一次网络往返上（见 `router/index.ts` 的守卫）。
   */
  async function load(): Promise<boolean> {
    if (inflight) return inflight
    loading.value = true
    lastError.value = ''
    inflight = (async () => {
      try {
        const res = await getAuthSession()
        user.value = res.authenticated && res.user ? res.user : null
        available.value = true
        return Boolean(user.value)
      } catch (err: unknown) {
        // 打不通 ≠ 未登录：留住上一次的 user，避免网络抖一下就把界面清空。
        available.value = false
        lastError.value = toErrorMessage(err, '加载会话失败')
        return false
      } finally {
        initialized.value = true
        loading.value = false
        loadedAt.value = Date.now()
        inflight = null
      }
    })()
    return inflight
  }

  /** 已经水合过就直接用缓存；给「不关心新鲜度」的调用方（组件挂载、路由守卫）用。 */
  async function ensureLoaded(): Promise<boolean> {
    if (initialized.value && !inflight) return authenticated.value
    return load()
  }

  /**
   * 后台低频重验：缓存超过 `maxAgeMs` 才补一次，**同步返回、不 await**。
   *
   * 用途是让「服务端把会话踢掉了」这件事最迟在一分钟内被发现，而代价不落在
   * 任何一次导航上——结果只影响**下一次**导航的判定。
   */
  function revalidateStale(maxAgeMs: number = SESSION_STALE_MS): void {
    if (!initialized.value || inflight) return
    if (Date.now() - loadedAt.value < maxAgeMs) return
    void load()
  }

  /**
   * 刷新完整用户信息与配额（/api/auth/me）。
   * 账号设置页、资料更新后调用。
   */
  async function refresh(): Promise<void> {
    if (!user.value && initialized.value) return
    loading.value = true
    lastError.value = ''
    try {
      const me = await getAuthMe()
      user.value = me.user
      quota.value = me.quota
      unread.value = me.unread
      available.value = true
    } catch (err: unknown) {
      lastError.value = toErrorMessage(err, '刷新用户信息失败')
    } finally {
      loading.value = false
    }
  }

  /**
   * 拉通知与全站公告。
   *
   * 这两条链路以前只建了 api 层没有消费方——管理员发的公告用户永远看不到，
   * 头像角标恒为 0。壳层挂载后调一次，之后靠 `markRead` 手动同步。
   */
  async function loadNotifications(): Promise<void> {
    if (!user.value) return
    try {
      const res = await getNotifications()
      notifications.value = res.items
      announcements.value = res.announcements
      unread.value = res.unread
    } catch (err: unknown) {
      // 通知不是主流程，失败只记不弹——弹出来会盖住用户正在做的事。
      lastError.value = toErrorMessage(err, '加载通知失败')
    }
  }

  async function markRead(): Promise<void> {
    if (!unread.value) return
    const now = new Date().toISOString()
    unread.value = 0
    notifications.value = notifications.value.map((item) =>
      item.read_at ? item : { ...item, read_at: now },
    )
    try {
      await markNotificationsRead()
    } catch (err: unknown) {
      lastError.value = toErrorMessage(err, '标记已读失败')
      await loadNotifications()
    }
  }

  /**
   * 登出并清理当前用户状态。
   */
  async function logout(): Promise<void> {
    loading.value = true
    lastError.value = ''
    try {
      await apiLogout()
    } finally {
      user.value = null
      quota.value = null
      unread.value = 0
      notifications.value = []
      announcements.value = []
      loading.value = false
    }
  }

  /**
   * 更新个人资料并同步到 store。
   */
  async function patchProfile(payload: {
    display_name?: string
    bio?: string
    avatar_url?: string
    username?: string
  }): Promise<UserProfile> {
    const updated = await apiPatchProfile(payload)
    user.value = updated
    return updated
  }

  function setUser(newUser: UserProfile | null): void {
    user.value = newUser
  }

  return {
    user,
    quota,
    unread,
    notifications,
    announcements,
    loading,
    initialized,
    lastError,
    available,
    authenticated,
    isAdmin,
    mustChangePassword,
    load,
    ensureLoaded,
    revalidateStale,
    refresh,
    loadNotifications,
    markRead,
    logout,
    patchProfile,
    setUser,
  }
})
