/**
 * 策稿工作台的请求/响应包装：技能详情、试跑（preview）、保存（upsert）、AI 生成
 * （generate），以及给人看的公式讲解。这些类型只在编辑期存在，形状跟着接口走；
 * 落地后的真值在 `manifest.ts` 与 `strategy.ts`。
 */

import type {
  EntryTiming,
  ScreenSkillAdjust,
  ScreenSkillDialect,
  ScreenSkillRuntime,
} from './enums'
import type {
  ScreenSkillDataSpec,
  ScreenSkillDerivedInfo,
  ScreenSkillDiagnostic,
  ScreenSkillLogic,
  ScreenSkillManifest,
  ScreenSkillReference,
} from './manifest'
import type { ScreenResult } from './screenResult'
import type { UniverseSpec } from './universe'

export interface ScreenSkillExplanationStep {
  id: string
  title: string
  kind: 'signal' | 'factor' | 'intermediate'
  expression: string
  plain_text: string
  line: number | null
  fields: string[]
  functions: string[]
}

export interface ScreenSkillPreviewExplanation {
  mode: 'compiler' | 'manifest'
  summary: string
  steps: ScreenSkillExplanationStep[]
  data_requirements: {
    fields: string[]
    min_bars: number
    adjust: ScreenSkillAdjust
    universe: UniverseSpec | null
  }
  timing: {
    entry_timing: EntryTiming
    plain_text: string
  }
}

export interface ScreenSkillDetail {
  slug: string
  name: string
  description: string
  version?: string
  enabled?: boolean
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  formula?: string
  code?: string
  entrypoint?: string
  manifest: ScreenSkillManifest
  logic?: ScreenSkillLogic[]
  references?: ScreenSkillReference[]
  data?: ScreenSkillDataSpec
  ui?: Record<string, unknown> | null
  package_revision: string
  strategy_revision: string
  updated_at?: string
}

export interface ScreenSkillPreviewRun {
  trade_date?: string
  codes?: string[]
  universe?: UniverseSpec
}

export interface ScreenSkillPreviewResponse {
  ok: boolean
  diagnostics: ScreenSkillDiagnostic[]
  derived?: ScreenSkillDerivedInfo | null
  run_result?: ScreenResult | null
  package_revision?: string
  strategy_revision?: string
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  code?: string
  logic?: ScreenSkillLogic[]
  references?: ScreenSkillReference[]
  data?: ScreenSkillDataSpec
  explanation?: ScreenSkillPreviewExplanation | null
}

export interface ScreenSkillUpsertPayload {
  slug: string
  name: string
  description: string
  version?: string
  enabled?: boolean
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  formula?: string
  code?: string
  entrypoint?: string
  manifest: ScreenSkillManifest
  ui?: Record<string, unknown> | null
}

export interface ScreenSkillGenerateRequest {
  source_type: 'description' | 'tdx' | 'ths' | 'python'
  source: string
  slug?: string
  name?: string
  description?: string
  entry_timing?: EntryTiming
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  entrypoint?: string
  references?: ScreenSkillReference[]
  provider?: string
  model?: string
  thinking?: string
}

export interface ScreenSkillGenerateResponse {
  ok: boolean
  diagnostics: ScreenSkillDiagnostic[]
  draft?: Partial<ScreenSkillUpsertPayload> | null
  derived?: ScreenSkillDerivedInfo | null
  strategy_revision?: string
}
