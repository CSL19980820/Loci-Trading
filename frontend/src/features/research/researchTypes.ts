import type {
  ResearchDimensionResult,
  ResearchDimensionSpec,
} from '@/shared/types/quant'

export type ResearchDimensionRow = ResearchDimensionSpec & {
  result?: ResearchDimensionResult
}
