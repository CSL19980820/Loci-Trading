<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/**
 * UiInput —— shadcn Input 构造：单行输入的统一样式。
 * 控件本身仍用 EP el-input（ div 换不掉），这里管的是外层一致的高度/字号/截断。
 * 用法：<UiInput><el-input … /></UiInput>，或直接用类名 input-cls。
 */
</script>

<template>
  <div :class="cn('flex min-w-0 flex-col gap-1')">
    <slot />
  </div>
</template>
