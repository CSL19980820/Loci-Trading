import { computed, reactive, ref } from 'vue'

import {
  getProviders,
  getStrategyJob,
  unbindStrategyJob,
  upsertStrategyJob,
} from '@/shared/api/quant'
import type { LlmProvider, StrategyInfo, StrategyJob } from '@/shared/types/quant'

const DEFAULT_FORM = {
  cron: '',
  auto_review: false,
  use_ai_pick: false,
  provider: '',
  model: '',
  thinking: '',
  trading_days: 60,
  top_n: 0,
  hold_days: 3,
  stop_loss_pct: -6,
  enabled: true,
}

export function useQuantConfig(
  strategies: { value: StrategyInfo[] },
  setBusy: (v: boolean) => void,
  setUnavailable: (msg: string) => void,
) {
  const configTarget = ref('')
  const configOpen = ref(false)
  const strategyJobs = ref<Record<string, StrategyJob>>({})
  const llmProviders = ref<LlmProvider[]>([])
  const configForm = reactive({ ...DEFAULT_FORM, top_n: 3, trading_days: 60 })

  const selectedProviderModels = computed(() => {
    const name = configForm.provider
    const hit = name
      ? llmProviders.value.find((item) => item.name === name)
      : llmProviders.value.find((item) => item.is_default) || llmProviders.value[0]
    return hit?.models ?? []
  })

  const configTitle = computed(() => {
    const hit = strategies.value.find((item) => item.slug === configTarget.value)
    return hit ? `${hit.name} — 定时选股配置` : '定时选股配置'
  })

  function resetForm(): void {
    Object.assign(configForm, { ...DEFAULT_FORM })
  }

  async function openConfig(slug: string): Promise<void> {
    configTarget.value = slug
    configOpen.value = true
    try {
      const [job, providers] = await Promise.all([getStrategyJob(slug), getProviders().catch(() => [])])
      llmProviders.value = providers
      strategyJobs.value[slug] = job
      if (job.bound) {
        const cfg = job.config ?? {}
        configForm.cron = job.cron ?? ''
        configForm.auto_review = Boolean(cfg.record_candidates)
        configForm.use_ai_pick = Boolean(cfg.use_ai_pick)
        configForm.provider = String(cfg.provider ?? '')
        configForm.model = String(cfg.model ?? '')
        configForm.thinking = String(cfg.thinking ?? '')
        configForm.trading_days = Number(cfg.trading_days ?? 60)
        configForm.top_n = Number(cfg.top_n ?? 0)
        configForm.hold_days = Number(cfg.hold_days ?? 3)
        configForm.stop_loss_pct = cfg.stop_loss_pct !== undefined ? Number(cfg.stop_loss_pct) : -6
        configForm.enabled = job.enabled
      } else {
        resetForm()
        configForm.top_n = 0
      }
    } catch {
      resetForm()
      configForm.top_n = 0
    }
  }

  async function saveConfig(slug: string): Promise<void> {
    setBusy(true)
    setUnavailable('')
    try {
      const job = await upsertStrategyJob(slug, {
        cron: configForm.cron,
        auto_review: configForm.auto_review,
        use_ai_pick: configForm.use_ai_pick,
        provider: configForm.provider,
        model: configForm.model,
        thinking: configForm.thinking,
        trading_days: configForm.trading_days,
        top_n: configForm.top_n,
        hold_days: configForm.hold_days,
        stop_loss_pct: configForm.stop_loss_pct,
        enabled: configForm.enabled,
      })
      strategyJobs.value[slug] = job
      configOpen.value = false
      configTarget.value = ''
    } catch (e: unknown) {
      setUnavailable(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function removeConfig(slug: string): Promise<void> {
    setBusy(true)
    try {
      await unbindStrategyJob(slug)
      strategyJobs.value[slug] = await getStrategyJob(slug)
      configOpen.value = false
      configTarget.value = ''
    } catch (e: unknown) {
      setUnavailable(e instanceof Error ? e.message : '删除失败')
    } finally {
      setBusy(false)
    }
  }

  return {
    configTarget,
    configOpen,
    strategyJobs,
    llmProviders,
    configForm,
    selectedProviderModels,
    configTitle,
    openConfig,
    saveConfig,
    removeConfig,
  }
}
