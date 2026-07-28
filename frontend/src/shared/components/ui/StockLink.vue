<script setup lang="ts">
withDefaults(
  defineProps<{
    code: string
    name?: string | null
    /** Stop click bubbling (e.g. inside clickable table rows). */
    stop?: boolean
  }>(),
  {
    name: null,
    stop: false,
  },
)
</script>

<template>
  <RouterLink
    :to="`/archive/${code}`"
    class="stock-link"
    @click="stop ? ($event.stopPropagation()) : undefined"
  >
    <template v-if="name">{{ name }} <span class="code">{{ code }}</span></template>
    <template v-else>{{ code }}</template>
  </RouterLink>
</template>
