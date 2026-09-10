/**
 * 后端 API 上的字面量枚举，独立成文件是因为下面每一个领域文件都要引它：
 * 放在任何一个领域文件里都会让另外九个反向依赖那个领域。这里只放没有任何
 * 依赖的叶子类型，切断领域文件之间的传递依赖。
 */

export type BoardBucket = 'main' | 'chi_next' | 'star' | 'bse'
export type EntryTiming = 'open' | 'close' | 'next_open' | 'next_dip'
export type ScreenSkillRuntime = 'formula' | 'python'
export type ScreenSkillDialect = 'loci' | 'tdx' | 'ths' | 'python'
export type ScreenSkillAdjust = 'qfq' | 'hfq' | 'none'
export type ScreenSkillSourceKind = 'formula' | 'python' | 'builtin'
export type ScreenSkillParamType = 'int' | 'float' | 'bool'
