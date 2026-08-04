<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import { strategyLabel } from '@/shared/lib/format'
import { useScreenRunStore } from '@/shared/stores/screenRun'

const store = useScreenRunStore()
const { running, busyStrategy, percent, snap } = storeToRefs(store)
const route = useRoute()
const router = useRouter()

const strategyName = computed(() => strategyLabel(busyStrategy.value))
const onWorkbench = () => route.name === 'screen-history'

function goProgress(): void {
  void router.push({ name: 'screen-history' })
}
</script>

<template>
  <el-button
    v-if="running && !onWorkbench()"
    native-type="button"
    class="screen-run-chip"
    @click="goProgress"
  >
    <span class="screen-run-chip__pulse" aria-hidden="true" />
    <span class="screen-run-chip__label">
      选股进行中
      <strong v-if="busyStrategy">{{ strategyName }}</strong>
      · {{ percent }}%
    </span>
    <span class="screen-run-chip__hint">{{ snap?.message || '点此看进度' }}</span>
  </el-button>
</template>

<style scoped>
.screen-run-chip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem 0.75rem;
  width: 100%;
  margin: 0;
  padding: 0.45rem 0.85rem;
  border: 1px solid color-mix(in srgb, var(--seal) 35%, var(--rule));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--seal-soft) 55%, var(--sheet));
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}

.screen-run-chip.el-button {
  height: auto;
  margin: 0;
  border-radius: var(--radius);
  --el-button-text-color: var(--ink);
  --el-button-hover-text-color: var(--ink);
}

.screen-run-chip:hover {
  border-color: var(--seal);
}

.screen-run-chip__pulse {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: var(--seal);
  flex-shrink: 0;
  animation: screen-run-blink 1.2s ease-in-out infinite;
}

.screen-run-chip__label {
  font-size: 0.84rem;
}

.screen-run-chip__label strong {
  margin: 0 0.15rem;
}

.screen-run-chip__hint {
  font-size: 0.75rem;
  color: var(--mist);
  margin-left: auto;
}

@keyframes screen-run-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .screen-run-chip__pulse {
    animation: none;
  }
}
</style>
