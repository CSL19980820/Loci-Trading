/**
 * 技能包自身的声明式契约：manifest、参数定义、逻辑条目、文献引用、数据需求，
 * 以及编译器回吐的诊断与推导结果。这一组是**存储与编译层**的真值，前端只读；
 * 工作台交互用的包装类型在 `authoring.ts`。
 */

import type {
  EntryTiming,
  ScreenSkillAdjust,
  ScreenSkillDialect,
  ScreenSkillParamType,
  ScreenSkillRuntime,
} from './enums'
import type { UniverseSpec } from './universe'

export interface ScreenSkillParamDef {
  type: ScreenSkillParamType
  default: number | boolean
  min?: number
  max?: number
  label?: string
}

export interface ScreenSkillLogic {
  id: string
  title: string
  expression: string
  explanation: string
  citations: string[]
}

export interface ScreenSkillReference {
  id: string
  title: string
  kind: string
  url?: string | null
  path?: string | null
  section?: string | null
  quote?: string | null
}

export interface ScreenSkillDataSpec {
  fields: string[]
  adjust: ScreenSkillAdjust
  universe?: UniverseSpec | null
}

export interface ScreenSkillManifest {
  schema_version: number
  entry_timing: EntryTiming
  min_bars: number
  params: Record<string, ScreenSkillParamDef>
  output: {
    signal: string
  }
  factors: string[]
  logic?: ScreenSkillLogic[] | null
  references?: ScreenSkillReference[] | null
  data?: ScreenSkillDataSpec | null
}

export interface ScreenSkillDiagnostic {
  code: string
  severity: 'error' | 'warning' | 'info' | string
  message: string
  line?: number
  column?: number
}

export interface ScreenSkillDerivedInfo {
  required_fields: string[]
  min_bars_required: number
  signal: string
  factors: string[]
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  data?: ScreenSkillDataSpec
}
