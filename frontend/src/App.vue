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
          <RouterLink
            v-if="firstPosition"
            :to="`/archive/${firstPosition.code}`"
            class="nav-link"
            active-class="nav-link-active"
          >
            档案
          </RouterLink>
        </nav>
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
  </template>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { logout } from '@/api/palace'
import { usePalaceStore } from '@/stores/palace'

const store = usePalaceStore()
const route = useRoute()
const router = useRouter()
const isPublicRoute = computed(() => route.meta.public === true)
const firstPosition = computed(() => store.firstPosition)

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