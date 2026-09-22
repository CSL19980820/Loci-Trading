<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppSidebar from '@/shared/components/layout/AppSidebar.vue'
import CommandPalette from '@/shared/components/layout/CommandPalette.vue'
import MobileBottomNav from '@/shared/components/layout/MobileBottomNav.vue'
import PageHost from '@/shared/components/layout/PageHost.vue'
import ConfirmHost from '@/shared/components/dialogs/ConfirmHost.vue'
import MarketBootstrapDialog from '@/shared/components/dialogs/MarketBootstrapDialog.vue'
import RecordDialog, { type RecordKind } from '@/shared/components/dialogs/RecordDialog.vue'
import { Toaster } from '@/shared/components/ui/sonner'
import { TooltipProvider } from '@/shared/components/ui/tooltip'
import { SidebarProvider } from '@/shared/components/ui/sidebar'
import { useShellNotices } from '@/shared/composables/useShellNotices'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { commandPaletteOpen, isPaletteHotkey, recordRequest, toggleCommandPalette } from '@/shared/lib/commandPalette'
import { pendingConfirm } from '@/shared/lib/confirm'
import { usePalaceStore } from '@/shared/stores/palace'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import { VISITOR_MODE } from '@/shared/composables/useAccess'
import { useUserStore } from '@/shared/stores/user'
import { navigationPending } from '@/shared/stores/navigation'
import WorkspaceLoading from '@/shared/components/ui/WorkspaceLoading.vue'
import { useMobileViewport } from '@/shared/composables/useMobileViewport'

useMobileViewport()

// 助手树很重（marked + dompurify + 整棵 Assistant 子树），静态 import 会把它全部钉进首屏 chunk。
const AssistantHost = defineAsyncComponent(() => import('@/features/ai/AssistantHost.vue'))

const store = usePalaceStore()
const userStore = useUserStore()
provide(VISITOR_MODE, computed(() => userStore.isVisitor))
const screenRun = useScreenRunStore()
const route = useRoute()
/** 补行情进行中时退出要拦一下：进度只在补完才落库 */
const { syncing } = useMarketSyncGate()
/** pathname 兜底：第二 WebView 偶发路由名不是 peek 时仍走公开壳 */
const isPeekWindow = typeof location !== 'undefined' && location.pathname.startsWith('/peek')
const isPublicRoute = computed(() => route.meta.public === true || route.name === 'peek' || isPeekWindow)

const recordOpen = ref(false)
const recordKind = ref<RecordKind>('candidate')
const sidebarRef = ref<InstanceType<typeof AppSidebar> | null>(null)

/*
 * 跨页状态（初始密码 / 加载失败 / 补行情 / 选股在跑）以前挤在一条 34px 定高的状态轨里，
 * 每页都被它压掉一行内容。现在全部走 toast 气泡：不占版面，有状态才出现。
 */
useShellNotices({ reload: () => reloadRoute() })

function openRecord(kind: RecordKind): void {
  if (!userStore.canWrite) return
  recordKind.value = kind
  recordOpen.value = true
}

function onRecorded(): void {
  if (route.name === 'archive') {
    store.invalidateArchive(String(route.params.code ?? ''))
  }
  void store.loadRoute(route, true)
}

function isTypingContext(): boolean {
  const el = document.activeElement
  if (!el || !(el instanceof HTMLElement)) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (el.isContentEditable) return true
  return false
}

function modalOpen(): boolean {
  return Boolean(
    document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]') ||
      pendingConfirm.value,
  )
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if (isPublicRoute.value) return
  // ⌘K 在任何上下文都可用（包括输入框里），只在别的模态打开时让位
  if (isPaletteHotkey(event)) {
    if (!commandPaletteOpen.value && modalOpen()) return
    event.preventDefault()
    toggleCommandPalette()
    return
  }
  if (isTypingContext()) return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (modalOpen()) return

  if (!userStore.canWrite) return
  const key = event.key.toLowerCase()
  if (key === 'c') {
    event.preventDefault()
    openRecord('candidate')
  } else if (key === 'p') {
    event.preventDefault()
    openRecord('plan')
  }
}

function onQuitWhileSyncing(event: BeforeUnloadEvent): void {
  if (!syncing.value) return
  event.preventDefault()
  event.returnValue = ''
}

let heartbeat: ReturnType<typeof setInterval> | undefined
let expiring = false
function expireSession(): void {
  if (isPublicRoute.value || expiring) return
  expiring = true
  recordOpen.value = false
  commandPaletteOpen.value = false
  userStore.setUser(null)
  // Full navigation disposes all account-scoped Pinia, KeepAlive and query caches.
  window.location.replace('/login?reason=session-ended')
}
async function revalidateSession(): Promise<void> {
  if (isPublicRoute.value || document.hidden || !userStore.authenticated) return
  await userStore.load()
  if (userStore.available && !userStore.authenticated) expireSession()
}
onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('beforeunload', onQuitWhileSyncing)
  window.addEventListener('pagehide', onQuitWhileSyncing)
  window.addEventListener('focus', revalidateSession)
  window.addEventListener('loci:session-expired', expireSession)
  heartbeat = setInterval(() => { if (userStore.isVisitor) void revalidateSession() }, 10_000)
  if (userStore.canWrite) void screenRun.hydrate()
})

onUnmounted(() => {
  clearInterval(heartbeat)
  window.removeEventListener('focus', revalidateSession)
  window.removeEventListener('loci:session-expired', expireSession)
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('beforeunload', onQuitWhileSyncing)
  window.removeEventListener('pagehide', onQuitWhileSyncing)
})

watch(
  () => ({ name: route.name, path: route.fullPath, public: route.meta.public === true }),
  ({ public: isPublic }) => {
    if (isPublic) return
    void store.loadRoute(route, true)
  },
  { immediate: true },
)

// 命令面板里的「记一条候选 / 预案」：面板不持有弹窗，抛请求回壳层
watch(recordRequest, (req) => {
  if (req) openRecord(req.kind)
})

/** 轨上的「重试」与「刷新」是同一件事：清掉错误再按当前路由重拉 */
function reloadRoute(): void {
  store.clearError()
  void store.loadRoute(route, true)
}

function openSidebarDialog(which: 'themeOpen'): void {
  const sidebar = sidebarRef.value
  if (sidebar) sidebar[which] = true
}
</script>

<template>
  <RouterView v-if="isPublicRoute" />
  <TooltipProvider v-else>
    <a class="skip-link" href="#main-content">跳至主内容</a>
    <SidebarProvider :key="userStore.user?.id || 'anonymous'" class="app-shell app-shell--with-mobile-nav min-h-0" style="--sidebar-width:224px;--sidebar-width-icon:60px">
      <AppSidebar ref="sidebarRef" />
      <section class="workspace">
        <!-- 加载进度：2px 细线，绝对定位吸在主区顶边，不参与排版 -->
        <div v-if="store.loading || navigationPending" class="load-line" role="progressbar" aria-label="正在加载本页数据" />

        <main id="main-content" tabindex="-1" class="main-content">
          <div class="page-host" :aria-busy="navigationPending" :inert="navigationPending">
            <RouterView v-slot="{ Component, route: rv }">
              <PageHost :component="Component" :route="rv" />
            </RouterView>
          </div>
          <div v-if="navigationPending" class="route-loading"><WorkspaceLoading /></div>
        </main>
      </section>
    </SidebarProvider>
    <RecordDialog v-if="userStore.canWrite" v-model="recordOpen" :kind="recordKind" @saved="onRecorded" />
    <MarketBootstrapDialog v-if="userStore.canWrite" />
    <CommandPalette @reload="reloadRoute" @theme="openSidebarDialog('themeOpen')" />

    <MobileBottomNav />
    <AssistantHost :key="userStore.user?.id" />
  </TooltipProvider>
  <!--
    气泡放右下角、左移让开助手浮球（浮球固定在右 24px、宽 48px）：
    顶部留给页面标题与动作，常驻提醒不挡它们。
  -->
  <Toaster position="bottom-right" :offset="{ bottom: 32, right: 88 }" :duration="3200" />
  <ConfirmHost />
</template>

<style scoped>
.main-content { position: relative; }
.route-loading { position: absolute; inset: 0; z-index: 2; display: flex; padding: 0 var(--gap-6); background: var(--surface-canvas); }
.workspace {
  position: relative;
}

/* 2px 进度线：绝对定位吸在顶边，不占布局 */
.load-line {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  z-index: 3;
  height: 2px;
  overflow: hidden;
  background: color-mix(in oklab, var(--seal) 15%, transparent);
  pointer-events: none;
}

.load-line::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 28%;
  border-radius: 2px;
  background: linear-gradient(90deg, transparent, var(--seal), var(--seal));
  animation: load-line-slide 1.1s linear infinite;
}

@keyframes load-line-slide {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(460%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .load-line::after {
    width: 100%;
    animation: none;
    opacity: 0.55;
  }
}
</style>
