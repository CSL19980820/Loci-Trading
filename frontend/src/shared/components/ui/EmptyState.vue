<script setup lang="ts">
withDefaults(
  defineProps<{
    description?: string
    reason?: string
    eta?: string
    imageSize?: number
  }>(),
  {
    // 默认值不该是一句可以直接交付的墓碑：调用方应当讲清「这里会出现什么」
    description: '这里还没有记录',
    imageSize: 96,
  },
)
</script>

<template>
  <el-empty :description="description" :image-size="imageSize">
    <!--
      不用 EP 自带插图：那张灰蓝色团块落在纸面上像污渍，且不跟主题走。
      换成一枚空账页——留白处的横线与页面底纹同源，空态因此读作「还没写」而非「坏了」。
    -->
    <template #image>
      <svg class="empty-mark" viewBox="0 0 64 64" role="img" aria-hidden="true" focusable="false">
        <rect
          x="12.5"
          y="6.5"
          width="39"
          height="51"
          rx="3"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
        />
        <g stroke="currentColor" stroke-width="1.3" stroke-linecap="round" opacity="0.55">
          <line x1="20" y1="21" x2="44" y2="21" />
          <line x1="20" y1="30" x2="44" y2="30" />
          <line x1="20" y1="39" x2="36" y2="39" />
        </g>
        <rect class="empty-mark__seal" x="36" y="44" width="8" height="8" rx="1.5" />
      </svg>
    </template>
    <template v-if="reason || eta || $slots.default" #default>
      <p v-if="reason" class="empty-reason">{{ reason }}</p>
      <p v-if="eta" class="empty-eta">预计：{{ eta }}</p>
      <slot />
    </template>
  </el-empty>
</template>

<style scoped>
.empty-mark {
  width: 100%;
  height: 100%;
  color: var(--rule);
}

.empty-mark__seal {
  fill: var(--seal);
  opacity: 0.32;
}

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
