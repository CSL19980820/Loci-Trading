/**
 * 编辑器补全目录：运行时、方言、字段、函数、代码片段。它只服务 Monaco 的
 * 补全与插入，和运行选股、落库都无关；单独成文件让 Monaco 侧可以只引这一支。
 */

import type { ScreenSkillDialect, ScreenSkillRuntime } from './enums'
import type { ScreenSkillParamDef } from './manifest'

export interface ScreenSkillCatalogRuntime {
  id: ScreenSkillRuntime
  label: string
  summary: string
  dialects: ScreenSkillDialect[]
}

export interface ScreenSkillCatalogDialect {
  id: ScreenSkillDialect
  runtime: ScreenSkillRuntime
  label: string
  summary: string
}

export interface ScreenSkillCatalogField {
  name: string
  label: string
  summary: string
  source: string
}

export interface ScreenSkillCatalogFunction {
  name: string
  category: string
  signature: string
  summary: string
  description: string
  insert_text: string
  examples: string[]
  dialects: ScreenSkillDialect[]
  source: string
}

export interface ScreenSkillCatalogSnippet {
  id: string
  title: string
  runtime: ScreenSkillRuntime
  dialect: ScreenSkillDialect
  summary: string
  code: string
  required_fields: string[]
  params: Record<string, ScreenSkillParamDef>
  factors: string[]
}

export interface ScreenSkillCatalog {
  runtimes: ScreenSkillCatalogRuntime[]
  dialects: ScreenSkillCatalogDialect[]
  fields: ScreenSkillCatalogField[]
  functions: ScreenSkillCatalogFunction[]
  snippets: ScreenSkillCatalogSnippet[]
}
