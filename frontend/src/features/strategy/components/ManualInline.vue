<script setup lang="ts">
import { computed } from 'vue'

import { parseInline, type InlineSeg } from '../composables/skillManual'

const props = defineProps<{ text: string }>()

const segs = computed((): InlineSeg[] => parseInline(props.text))

function safeHref(href: string): string {
  const t = href.trim()
  if (/^https?:\/\//i.test(t) || t.startsWith('/') || t.startsWith('#')) return t
  return '#'
}
</script>

<template>
  <template v-for="(seg, i) in segs" :key="i">
    <strong v-if="seg.type === 'strong'">{{ seg.text }}</strong>
    <em v-else-if="seg.type === 'em'">{{ seg.text }}</em>
    <code v-else-if="seg.type === 'code'" class="md-inline-code">{{ seg.text }}</code>
    <a
      v-else-if="seg.type === 'link'"
      class="md-inline-link"
      :href="safeHref(seg.href)"
      target="_blank"
      rel="noopener noreferrer"
    >{{ seg.text }}</a>
    <template v-else>{{ seg.text }}</template>
  </template>
</template>

<style scoped>
.md-inline-code {
  padding: 0.05em 0.3em;
  border-radius: 3px;
  background: var(--surface-sunken);
  font-family: var(--mono);
  font-size: 0.92em;
}
.md-inline-link {
  color: var(--seal-ink);
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
