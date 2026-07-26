<template>
  <RouterView v-if="isPublicRoute" />
  <template v-else>
    <a class="skip-link" href="#main-content">跳至主内容</a>
    <div class="app-shell">
      <aside class="side-rail" aria-label="导航">
        <RouterLink class="brand" to="/" aria-label="首页">
          <span class="brand-mark" aria-hidden="true">潜</span>
          <strong>潜龙</strong>
        </RouterLink>
        <nav>
          <RouterLink to="/" class="nav-link" exact-active-class="nav-link-active">总览</RouterLink>
          <RouterLink to="/journal" class="nav-link" active-class="nav-link-active">交割</RouterLink>
          <RouterLink to="/pool" class="nav-link" active-class="nav-link-active">候选</RouterLink>
          <RouterLink to="/reviews" class="nav-link" active-class="nav-link-active">复盘</RouterLink>
          <RouterLink to="/quant" class="nav-link" active-class="nav-link-active">量化</RouterLink>
          <RouterLink to="/ops" class="nav-link" active-class="nav-link-active">运维</RouterLink>
          <RouterLink
            v-if="firstPosition"
            :to="`/archive/${firstPosition.code}`"
            class="nav-link"
            active-class="nav-link-active"
          >
            档案
          </RouterLink>
        </nav>

        <!-- 录入入口。这五类此前后端有接口、前端一个按钮都没有，
             是"线上只能看不能记，什么都要回本地 CLI"的直接原因。 -->
        <div class="rail-actions">
          <span class="rail-actions-label">记录</span>
          <button
            v-for="entry in recordEntries"
            :key="entry.kind"
            class="quiet-button rail-action"
            type="button"
            @click="openRecord(entry.kind)"
          >
            {{ entry.label }}
          </button>
        </div>
      </aside>

      <section class="workspace">
        <div v-if="store.loading" class="load-line" aria-hidden="true" />
        <p v-if="store.notice" class="toast" role="status">
          {{ store.notice }}
          <button type="button" aria-label="关闭" @click="store.clearNotice">×</button>
        </p>
        <p v-if="store.error" class="error-banner" role="alert">
          <span>{{ store.error }}</span>
          <span class="error-actions">
            <button type="button" class="quiet-button" @click="retryLoad">重试</button>
            <button type="button" aria-label="关闭" @click="store.clearError">×</button>
          </span>
        </p>
        <main id="main-content" tabindex="-1" class="main-content">
          <RouterView />
        </main>
        <footer class="app-foot">
          <button class="quiet-button" type="button" @click="signOut">退出</button>
        </footer>
      </section>
    </div>
    <RecordDialog v-model="recordOpen" :kind="recordKind" @saved="onRecorded" />
  </template>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { logout } from '@/api/palace'
import RecordDialog, { type RecordKind } from '@/components/RecordDialog.vue'
import { usePalaceStore } from '@/stores/palace'

const store = usePalaceStore()
const route = useRoute()
const router = useRouter()
const isPublicRoute = computed(() => route.meta.public === true)
const firstPosition = computed(() => store.firstPosition)

const recordEntries: { kind: RecordKind; label: string }[] = [
  { kind: 'candidate', label: '候选' },
  { kind: 'plan', label: '预案' },
  { kind: 'review', label: '复盘' },
  { kind: 'snapshot', label: '资产' },
  { kind: 'cashflow', label: '出入金' },
]
const recordOpen = ref(false)
const recordKind = ref<RecordKind>('candidate')

function openRecord(kind: RecordKind): void {
  recordKind.value = kind
  recordOpen.value = true
}

function onRecorded(): void {
  // 写入后刷新当前页，让新记录立刻出现，不用手动重载。
  void store.loadRoute(route, true)
}

watch(
  () => ({ name: route.name, path: route.fullPath, public: route.meta.public === true }),
  ({ public: isPublic }) => {
    if (isPublic) return
    // 路由变化需要刷新；同一 key 的并发请求由 store 序号丢弃过期响应。
    void store.loadRoute(route, true)
  },
  { immediate: true },
)

function retryLoad(): void {
  store.clearError()
  void store.loadRoute(route, true)
}

async function signOut(): Promise<void> {
  try {
    await logout()
  } finally {
    await router.replace('/login')
  }
}
</script>