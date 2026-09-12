import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { shareholderAssessmentApi } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

// 后置核验只作用于明确启用此规则的策略的研究列表，不进入矩阵回测。
export function useReviewedScores(strategyId: string | null, asOf: string, rows: any[]) {
  const query = useQuery({
    queryKey: QK.shareholderAssessments(strategyId ?? '', asOf),
    queryFn: () => shareholderAssessmentApi.list(strategyId!, asOf),
    enabled: strategyId === 'custom_mtxs8bfe' && !!asOf, staleTime: 10_000, retry: false,
  })
  return useMemo(() => {
    if (query.data ? !query.data.enabled : strategyId !== 'custom_mtxs8bfe') return rows
    return rows.map(row => {
      const review = query.data?.assessments[row.symbol]
      return { ...row, technical_sort_score: row.score,
        score: review?.scoring.final_score ?? null,
        shareholder_review: review ?? null, shareholder_review_required: true }
    })
  }, [rows, query.data, strategyId])
}
