<script setup lang="ts">
import { EditPen } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppSidebar from '@/shared/components/layout/AppSidebar.vue'
import MobileBottomNav from '@/shared/components/layout/MobileBottomNav.vue'
import MarketBootstrapDialog from '@/shared/components/dialogs/MarketBootstrapDialog.vue'
import RecordDialog, { type RecordKind } from '@/shared/components/dialogs/RecordDialog.vue'
import TradeDialog from '@/shared/components/dialogs/TradeDialog.vue'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { usePalaceStore } from '@/shared/stores/palace'

const store = usePalaceStore()
const route = useRoute()
const { syncing, busyLabel } = useMarketSyncGate()
const isPublicRoute = computed(() => route.meta.public === true)
const archivePath = computed(() =>
  store.firstPosition ? `/archive/${store.firstPosition.code}` : null,
)

const recordOpen = ref(false)
const recordKind = ref<RecordKind>('candidate')
const tradeOpen = ref(false)

function openRecord(kind: RecordKind): void {
  recordKind.value = kind
  recordOpen.value = true
}

function onRecorded(): void {
  void store.loadRoute(route, true)
}

function onTradeSaved(): void {
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
    ['n — 记成交', 'c — 写候选', 'p — 写预案', '? — 显示本帮助'].join('\n'),
    '键盘快捷键',
    { confirmButtonText: '知道了' },
  )
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if (isPublicRoute.value) return
  if (isTypingContext()) return
  if (event.ctrlKey || event.metaKey || event.altKey) return

  if (event.key === '?' || (event.shiftKey && event.key === '/')) {
    event.preventDefault()
    showShortcutHelp()
    return
  }

  const key = event.key.toLowerCase()
  if (key === 'n') {
    event.preventDefault()
    tradeOpen.value = true
  } else if (key === 'c') {
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

function retryLoad(): void {
  store.clearError()
  void store.loadRoute(route, true)
}
</script>

<template>
  <RouterView v-if="isPublicRoute" />
  <template v-else>
    <a class="skip-link" href="#main-content">跳至主内容</a>
    <div class="app-shell app-shell--with-mobile-nav">
      <AppSidebar :archive-path="archivePath" @record="openRecord" />

      <section class="workspace">
        <el-alert
          v-if="syncing"
          :title="busyLabel"
          type="warning"
          show-icon
          :closable="false"
          class="banner sync-banner"
        />
        <el-progress
          v-if="store.loading"
          :percentage="100"
          :indeterminate="true"
          :show-text="false"
          :stroke-width="3"
          class="load-bar"
        />
        <el-alert
          v-if="store.notice"
          :title="store.notice"
          type="success"
          show-icon
          closable
          class="banner"
          @close="store.clearNotice"
        />
        <el-alert
          v-if="store.error"
          :title="store.error"
          type="error"
          show-icon
          class="banner"
          @close="store.clearError"
        >
          <template #default>
            <el-button size="small" @click="retryLoad">重试</el-button>
          </template>
        </el-alert>
        <main id="main-content" tabindex="-1" class="main-content">
          <div class="page-host">
            <RouterView />
          </div>
        </main>
      </section>
    </div>
    <RecordDialog v-model="recordOpen" :kind="recordKind" @saved="onRecorded" />
    <TradeDialog v-model="tradeOpen" @saved="onTradeSaved" />
    <MarketBootstrapDialog />

    <MobileBottomNav :archive-path="archivePath" />

    <div class="record-fab">
      <el-dropdown trigger="click" @command="openRecord">
        <el-button type="primary" circle size="large" aria-label="记一笔">
          <el-icon><EditPen /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="candidate">候选</el-dropdown-item>
            <el-dropdown-item command="plan">预案</el-dropdown-item>
            <el-dropdown-item command="review">复盘</el-dropdown-item>
            <el-dropdown-item command="snapshot">资产</el-dropdown-item>
            <el-dropdown-item command="cashflow">出入金</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </template>
</template>
