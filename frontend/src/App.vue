<script setup lang="ts">
import { Key, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppSidebar from '@/shared/components/layout/AppSidebar.vue'
import MobileBottomNav from '@/shared/components/layout/MobileBottomNav.vue'
import NotificationCenter from '@/shared/components/layout/NotificationCenter.vue'
import PageHost from '@/shared/components/layout/PageHost.vue'
import ScreenRunChip from '@/shared/components/layout/ScreenRunChip.vue'
import MarketBootstrapDialog from '@/shared/components/dialogs/MarketBootstrapDialog.vue'
import RecordDialog, { type RecordKind } from '@/shared/components/dialogs/RecordDialog.vue'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { usePalaceStore } from '@/shared/stores/palace'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import { useUserStore } from '@/shared/stores/user'

// 助手树很重（marked + dompurify + vue-element-plus-x + 整棵 Assistant 子树），
// 静态 import 会把它全部钉进首屏 chunk——而多数会话里用户根本不开助手。
// 浮球本身在 AssistantHost 内，异步加载后首帧晚一点出现是可接受代价。
const AssistantHost = defineAsyncComponent(() => import('@/features/ai/AssistantHost.vue'))

const store = usePalaceStore()
const screenRun = useScreenRunStore()
const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const { syncing, busyLabel, syncPercent } = useMarketSyncGate()
/** pathname 兜底：第二 WebView 偶发路由名不是 peek 时仍走公开壳，避免底栏+启动中叠字 */
const isPeekWindow = typeof location !== 'undefined' && location.pathname.startsWith('/peek')
const isPublicRoute = computed(
  () => route.meta.public === true || route.name === 'peek' || isPeekWindow,
)
const archiveOpen = computed(() => route.name === 'archive')
/** 档案蒙版 z-index=var(--z-archive)；打开档案时抬高 EP 弹层起点到 var(--z-archive-popup)，避免记一笔/分时被盖住 */
const epPopupZIndex = computed(() => (archiveOpen.value ? 8200 : 2000))

const recordOpen = ref(false)
const recordKind = ref<RecordKind>('candidate')

/*
 * —— 状态轨（.status-rail）——
 *
 * 旧壳把「改密码 / 补行情 / 选股在跑 / 页面加载 / 加载失败」各做成一条横幅依次
 * 摞在正文上方：全出现时吃掉小半屏，全不出现时还留着一堆 margin 空壳。现在统一
 * 收进一条 26px 定高的轨——**有内容才渲染**，chip 横排，按下面的优先级从左到右：
 *
 *   1 阻塞性（必须改密码）→ 2 错误 → 3 进行中任务（补行情 / 选股）→ 4 提示（未读消息）
 *
 * 模板里的书写顺序就是这个优先级，不要在中间插新 chip；加新状态先想清它属于哪一档。
 */

/**
 * 选股 chip 是否占位。判定必须与 ScreenRunChip 内部的 `onWorkbench()` 保持一致：
 * 选股工作台自己有整块进度面板，轨上不重复提示——否则这里判「有」、组件判「无」，
 * 就会渲染出一条什么都没有的空轨。
 */
const screenChipActive = computed(
  () => route.name !== 'screen-history' && (screenRun.running || screenRun.abandoned != null),
)
const hasBlocking = computed(() => userStore.mustChangePassword)
const hasError = computed(() => Boolean(store.error))
const hasUnread = computed(() => userStore.unread > 0)
const railVisible = computed(() => {
  if (hasBlocking.value || hasError.value) return true
  return syncing.value || screenChipActive.value || hasUnread.value
})
/** 轨上只显示整数百分比（等宽对齐）；越界值一律夹到 0–100 */
const syncPct = computed(() => Math.min(100, Math.max(0, Math.round(syncPercent.value || 0))))

function openRecord(kind: RecordKind): void {
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

function showShortcutHelp(): void {
  void ElMessageBox.alert(
    ['c — 写候选', 'p — 写预案', '? — 显示本帮助'].join('\n'),
    '键盘快捷键',
    { confirmButtonText: '知道了' },
  )
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if (isPublicRoute.value) return
  if (isTypingContext()) return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  // 已有弹层时不再响应 c/p，否则会在对话框上再叠一层
  if (document.querySelector('.el-overlay')) return

  if (event.key === '?' || (event.shiftKey && event.key === '/')) {
    event.preventDefault()
    showShortcutHelp()
    return
  }
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

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('beforeunload', onQuitWhileSyncing)
  window.addEventListener('pagehide', onQuitWhileSyncing)
  void screenRun.hydrate()
})

onUnmounted(() => {
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

/** 轨上的「重试」与「刷新」是同一件事：清掉错误再按当前路由重拉 */
function reloadRoute(): void {
  store.clearError()
  void store.loadRoute(route, true)
}

function goAccount(): void {
  void router.push('/account')
}
</script>

<template>
  <RouterView v-if="isPublicRoute" />
  <el-config-provider v-else :z-index="epPopupZIndex">
    <a class="skip-link" href="#main-content">跳至主内容</a>
    <div
      class="app-shell"
      :class="{
        'app-shell--with-mobile-nav': true,
      }"
    >
         <AppSidebar />
      <section class="workspace" :class="{ 'workspace--railed': railVisible }">
        <div
          v-if="railVisible"
          class="status-rail"
          role="status"
          aria-live="polite"
          aria-label="全局状态"
        >
          <!-- 1 阻塞：长文案压成四个字，全文进 tooltip，动作是一颗 link 按钮 -->
          <el-tooltip
            v-if="hasBlocking"
            content="账号仍在用初始密码或已被重置，请尽快改掉再继续使用"
            placement="bottom-start"
            :show-after="150"
          >
            <div class="rail-chip rail-chip--block">
              <el-icon class="rail-chip__icon"><Key /></el-icon>
              <span class="rail-chip__text">初始密码</span>
              <el-button
                link
                class="rail-chip__act"
                aria-label="去账号页修改初始密码"
                @click="goAccount"
              >
                去修改
              </el-button>
            </div>
          </el-tooltip>

          <!-- 2 错误：轨上只留四个字，后端原文进 tooltip -->
          <el-tooltip v-if="hasError" :content="store.error" placement="bottom" :show-after="150">
            <div class="rail-chip rail-chip--error">
              <el-icon class="rail-chip__icon"><WarningFilled /></el-icon>
              <span class="rail-chip__text">加载失败</span>
              <el-button
                link
                class="rail-chip__act"
                aria-label="重新加载本页数据"
                @click="reloadRoute"
              >
                重试
              </el-button>
              <el-button
                link
                class="rail-chip__act rail-chip__act--mute"
                aria-label="忽略这条错误"
                @click="store.clearError"
              >
                忽略
              </el-button>
            </div>
          </el-tooltip>

          <!-- 3 进行中：补行情 -->
          <el-tooltip
            v-if="syncing"
            :content="busyLabel || '正在补行情'"
            placement="bottom"
            :show-after="150"
          >
            <div class="rail-chip rail-chip--busy">
              <span class="rail-chip__pulse" aria-hidden="true" />
              <span class="rail-chip__text">同步中</span>
              <span class="rail-chip__num">{{ syncPct }}%</span>
            </div>
          </el-tooltip>

          <!-- 3 进行中 / 4 提示：选股在跑，或刚被放弃的残影。组件自己判空 -->
          <ScreenRunChip />

          <span class="status-rail__fill" aria-hidden="true" />

          <NotificationCenter trigger />
          <el-tooltip content="刷新本页数据" placement="bottom-end" :show-after="150">
            <el-button link class="rail-icon" aria-label="刷新本页数据" @click="reloadRoute">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </el-tooltip>
        </div>

        <!--
          加载进度：2px 细线，绝对定位吸在状态轨底边（无轨时吸主区顶边）。
          它不参与 flex 排版，所以不会把正文往下顶，也不会在加载结束时抖一下。
        -->
        <div
          v-if="store.loading"
          class="load-line"
          role="progressbar"
          aria-label="正在加载本页数据"
        />

        <main id="main-content" tabindex="-1" class="main-content">
          <div class="page-host">
            <RouterView v-slot="{ Component, route: rv }">
              <PageHost :component="Component" :route="rv" />
            </RouterView>
          </div>
        </main>
      </section>
    </div>
    <RecordDialog v-model="recordOpen" :kind="recordKind" @saved="onRecorded" />
    <MarketBootstrapDialog />

    <MobileBottomNav />
    <AssistantHost />
  </el-config-provider>
</template>

<style scoped>
/* 进度线要相对主区定位；.workspace 其余排版仍在 style.base.css */
.workspace {
  position: relative;
}

/*
 * 一条轨，定高 --head-h(26px)，横向排 chip。刻意不给 margin：
 * 轨在就是 26px，轨不在就是 0，正文的起始位置只有这两种可能。
 */
.status-rail {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  height: var(--head-h);
  padding: 0 var(--gap-2);
  border-bottom: 1px solid var(--rule);
  background: var(--sheet-alt);
  overflow: hidden;
}

/* 左侧状态与右侧入口之间的弹性留白 */
.status-rail__fill {
  flex: 1 1 auto;
  min-width: 0;
}

.rail-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  flex: 0 1 auto;
  min-width: 0;
  height: 20px;
  padding: 0 var(--gap-1);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  color: var(--ink);
  font-size: var(--fs-kicker);
  line-height: 1;
  white-space: nowrap;
}

.rail-chip__text {
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail-chip__icon {
  flex-shrink: 0;
  font-size: var(--fs-aux);
}

.rail-chip__num {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

/* 阻塞：琥珀底 + 加粗，轨上唯一「必须动手」的一档（D1：不用红） */
.rail-chip--block {
  border-color: color-mix(in oklab, var(--warn) 45%, var(--rule));
  background: color-mix(in oklab, var(--warn) 10%, var(--sheet));
}

.rail-chip--block .rail-chip__icon {
  color: var(--warn);
}

.rail-chip--block .rail-chip__text {
  font-weight: 600;
}

/* 错误：不填底，只把边压重一档 + 琥珀图标，与阻塞档拉开区别 */
.rail-chip--error {
  border-color: var(--rule-strong);
}

.rail-chip--error .rail-chip__icon {
  color: var(--warn);
}

.rail-chip--busy {
  border-color: color-mix(in oklab, var(--seal) 35%, var(--rule));
  background: var(--seal-soft);
}

.rail-chip__pulse {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--seal);
  animation: rail-pulse 1.2s ease-in-out infinite;
}

/* chip 内动作：压成行内链接大小，不要 EP 默认的 28px 控件高 */
.rail-chip__act.el-button {
  height: auto;
  margin: 0;
  padding: 0;
  border: 0;
  font-size: var(--fs-kicker);
  vertical-align: baseline;
  --el-button-text-color: var(--seal);
  --el-button-hover-text-color: var(--seal-ink);
}

.rail-chip__act.el-button + .rail-chip__act.el-button {
  margin-left: var(--gap-1);
}

.rail-chip__act--mute.el-button {
  --el-button-text-color: var(--mist);
  --el-button-hover-text-color: var(--ink);
}

.rail-icon.el-button {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  margin: 0;
  padding: 0;
  border-radius: var(--radius);
  --el-button-text-color: var(--mist);
  --el-button-hover-text-color: var(--seal);
}

.rail-icon.el-button:hover {
  background: var(--seal-soft);
}

.rail-icon .el-icon {
  font-size: var(--fs-aux);
}

/*
 * 2px 进度线：绝对定位，不占布局。无轨时吸主区顶边，有轨时压住轨底那条 1px
 * hairline——加载时它变成进度条，加载完又变回分隔线，正文一帧都不位移。
 */
/* 壳内部 2px 进度线，不进全局 --z-* 序列 */
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

.workspace--railed .load-line {
  top: calc(var(--head-h) - 1px);
}

.load-line::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 28%;
  background: var(--seal);
  animation: load-line-slide 1.1s linear infinite;
}

@keyframes rail-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
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
  .rail-chip__pulse {
    animation: none;
  }

  .load-line::after {
    width: 100%;
    animation: none;
    opacity: 0.55;
  }
}

</style>
