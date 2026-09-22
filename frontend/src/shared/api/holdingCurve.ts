import { quantRequest, query } from './quant_client'
import type { HoldingCurve } from '@/shared/types/holdingCurve'

export const getHoldingCurve = (code: string, days: number, signal?: AbortSignal) =>
  quantRequest<HoldingCurve>(`/ops/guardian/holding-curve${query({ code, days })}`, { signal })
