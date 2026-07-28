<script setup lang="ts">
withDefaults(
  defineProps<{
    description?: string
    reason?: string
    eta?: string
    imageSize?: number
  }>(),
  {
    description: '暂无数据',
    imageSize: 96,
  },
)
</script>

<template>
  <el-empty :description="description" :image-size="imageSize">
    <template v-if="reason || eta || $slots.default" #default>
      <p v-if="reason" class="empty-reason">{{ reason }}</p>
      <p v-if="eta" class="empty-eta">预计：{{ eta }}</p>
      <slot />
    </template>
  </el-empty>
</template>

<style scoped>
.empty-reason {
  margin: 0 0 0.35rem;
  color: var(--mist);
  font-size: 0.875rem;
  line-height: 1.5;
}

.empty-eta {
  margin: 0 0 0.75rem;
  color: var(--dim);
  font-size: 0.8125rem;
  line-height: 1.45;
}
</style>
