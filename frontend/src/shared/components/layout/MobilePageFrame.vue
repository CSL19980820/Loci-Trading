<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ title?: string; reading?: boolean }>()
const scroller = ref<HTMLElement>()
defineExpose({ scrollToTop: () => scroller.value?.scrollTo({ top: 0, behavior: 'auto' }) })
</script>

<template>
  <section class="page-fill mobile-page" :class="{ 'mobile-page--reading': reading }">
    <header v-if="title || $slots.header || $slots.actions" class="mobile-page__header">
      <slot name="header"><h1>{{ title }}</h1></slot>
      <div v-if="$slots.actions" class="mobile-page__actions"><slot name="actions" /></div>
    </header>
    <div v-if="$slots.navigation" class="mobile-page__navigation"><slot name="navigation" /></div>
    <div v-if="$slots.toolbar" class="mobile-page__toolbar"><slot name="toolbar" /></div>
    <div ref="scroller" class="mobile-page__content" data-page-scroll>
      <slot />
    </div>
    <footer v-if="$slots.footer" class="mobile-page__footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.mobile-page { min-width:0; height:100%; gap:0; }
.mobile-page__header { display:flex; align-items:center; justify-content:space-between; gap:10px; min-height:52px; flex:none; padding:6px 0; }
.mobile-page__header h1 { margin:0; font-size:18px; line-height:1.35; font-weight:650; letter-spacing:-.02em; }
.mobile-page__actions { display:flex; align-items:center; gap:5px; flex:none; }
.mobile-page__actions :deep(button) { min-height:40px; }
.mobile-page__navigation { flex:none; min-width:0; padding:0 0 8px; }
.mobile-page__navigation :deep(.page-tabs) { margin:0; }
.mobile-page__toolbar { display:flex; align-items:center; gap:8px; flex:none; padding:0 0 8px; min-width:0; }
.mobile-page__content { flex:1 1 0%; min-height:0; min-width:0; overflow-y:auto; overflow-x:hidden; overscroll-behavior-y:contain; scrollbar-width:thin; padding:0 0 14px; scroll-padding-block:8px; }
.mobile-page__content > :deep(*) { min-width:0; }
.mobile-page__footer { flex:none; padding:8px 0; border-top:1px solid var(--border-subtle); }
.mobile-page--reading .mobile-page__content { line-height:1.8; }
</style>
