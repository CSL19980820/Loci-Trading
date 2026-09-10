/**
 * Screen Skill / 选股 / 回测 相关类型的聚合入口，供 quant.ts re-export。
 *
 * 原来是一个 627 行的平铺文件，十个互不相干的领域挤在一起：改一个字段要在
 * 全文搜索里翻，读一个类型要滚过另外九组。现在按领域切到 `screenSkill/` 下，
 * 这里只做重导出——外部一律 `from '@/shared/types/screenSkill'`，调用方零改动，
 * 领域文件之间的依赖方向由 `enums.ts`（无依赖叶子）单向收口。
 */

export type * from './screenSkill/enums'
export type * from './screenSkill/universe'
export type * from './screenSkill/strategy'
export type * from './screenSkill/manifest'
export type * from './screenSkill/catalog'
export type * from './screenSkill/authoring'
export type * from './screenSkill/screenResult'
export type * from './screenSkill/screenRun'
export type * from './screenSkill/backtest'
export type * from './screenSkill/horizon'
