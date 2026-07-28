<script setup lang="ts">
import { BRAND_NAME } from '@/shared/lib/brand'
import {
  APP_CAPABILITIES,
  APP_RELEASE_SUMMARY,
  APP_RELEASED_AT,
  APP_VERSION,
} from '@/shared/lib/release'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const brandName = BRAND_NAME
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="版本"
    width="32rem"
    destroy-on-close
    class="version-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <header class="ver-hero">
      <div>
        <p class="ver-hero__brand">{{ brandName }}</p>
        <p class="ver-hero__ver mono">v{{ APP_VERSION }}</p>
      </div>
      <div class="ver-hero__meta">
        <span class="label">发布时间</span>
        <strong class="mono">{{ APP_RELEASED_AT }}</strong>
      </div>
    </header>

    <p class="ver-summary">{{ APP_RELEASE_SUMMARY }}</p>

    <section v-for="group in APP_CAPABILITIES" :key="group.title" class="cap-group">
      <h3>{{ group.title }}</h3>
      <ul>
        <li v-for="item in group.items" :key="item">{{ item }}</li>
      </ul>
    </section>

    <template #footer>
      <el-button type="primary" @click="emit('update:modelValue', false)">知道了</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.ver-hero {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 0.75rem;
}
.ver-hero__brand {
  margin: 0;
  font-size: 0.82rem;
  color: var(--mist);
}
.ver-hero__ver {
  margin: 0.15rem 0 0;
  font-size: 1.45rem;
  font-weight: 700;
  color: var(--ink);
}
.ver-hero__meta {
  display: grid;
  gap: 0.15rem;
  text-align: right;
}
.ver-hero__meta .label {
  font-size: 0.72rem;
  color: var(--mist);
}
.ver-summary {
  margin: 0 0 1rem;
  padding: 0.65rem 0.75rem;
  background: var(--panel-2);
  border-radius: var(--radius);
  border: 1px solid var(--rule);
  font-size: 0.88rem;
  color: var(--muted);
}
.cap-group {
  margin: 0 0 0.85rem;
}
.cap-group h3 {
  margin: 0 0 0.35rem;
  font-size: 0.84rem;
  font-weight: 650;
  color: var(--ink);
}
.cap-group ul {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--muted);
  font-size: 0.84rem;
  line-height: 1.55;
}
.mono {
  font-family: var(--mono);
}
</style>
