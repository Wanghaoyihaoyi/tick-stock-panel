import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSearch, Loader2 } from 'lucide-react'
import type { FrontendExtension, FrontendSlotContextMap } from '@/extensions/types'
import { disclosureResearchApi, shareholderAssessmentApi } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

function AssessmentSummary({ symbol, asOf }: { symbol: string; asOf: string }) {
  const query = useQuery({ queryKey: QK.shareholderAssessments('custom_mtxs8bfe', asOf),
    queryFn: () => shareholderAssessmentApi.list('custom_mtxs8bfe', asOf), enabled: !!asOf, staleTime: 10_000 })
  const record = query.data?.assessments[symbol]
  if (!record) return null
  const a = record.scoring
  const labels: Record<string, string> = { holder_count: '户数下降', top10_float_ratio: '十大流通占比', institution_float_ratio: '机构占比', new_institutions: '新进机构' }
  return <div className="rounded border border-accent/40 p-3 space-y-2">
    <h4 className="font-medium">筹码＋股东综合核验</h4>
    <p>筹码 {a.chip_score}/35 · 趋势 {a.trend_score}/25 · 股东 {a.shareholder_score ?? `${a.known_shareholder_score} 已知`}/25</p>
    <p className="text-accent">{a.final_score != null ? `最终评分 ${a.final_score.toFixed(2)} · ${a.grade}`
      : `参考评分 ${a.score_range[0].toFixed(2)}${a.score_range[0] === a.score_range[1] ? '' : `–${a.score_range[1].toFixed(2)}`} /100 · ${a.status === 'excluded' ? '否决' : '资料未齐，非最终评级'}`}</p>
    <div className="flex flex-wrap gap-3 text-xs">{Object.entries(a.factors).map(([key, f]) => <span key={key}>{labels[key] ?? key}：{f.score ?? '缺项'}/{f.max_score}</span>)}</div>
    <p className="text-xs text-secondary whitespace-pre-wrap">{record.review_note}</p>
    <div className="flex flex-wrap gap-3 text-xs">{record.review_sources.map(source => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">{source.title}（{source.published_on}）↗</a>)}</div>
    <p className="text-xs text-amber-500">{[...a.vetoes, ...a.missing].join('；')}</p>
  </div>
}

function ResearchPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false)
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
  const [asOf, setAsOf] = useState(today)
  const client = useQueryClient()
  const reports = useQuery({
    queryKey: QK.disclosureReports(symbol),
    queryFn: () => disclosureResearchApi.reports(symbol),
    enabled: open, staleTime: 60_000, retry: false,
  })
  const search = useMutation({
    mutationFn: ({ date, refresh }: { date: string; refresh: boolean }) =>
      disclosureResearchApi.research(symbol, date, refresh),
    onSuccess: () => client.invalidateQueries({ queryKey: QK.disclosureReports(symbol) }),
  })
  const report = reports.data?.reports.find(r => r.as_of === asOf)
  const error = search.error || reports.error
  return <section className="border-t border-border px-4 py-2 text-sm">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
      className="inline-flex items-center gap-2 text-accent hover:underline">
      <FileSearch size={16} />股东与公告核验{open ? ' · 收起' : ''}
    </button>
    {open && <div className="mt-3 max-h-[42vh] overflow-y-auto space-y-3 pr-2">
      <p className="text-xs text-muted">联网检索官方披露并保存资料。模型提取仍需核对原文，未找到不代表无风险，不计入筹码评分或历史回测。</p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-secondary">资料截止日（北京日终）
          <input aria-label="资料截止日" type="date" value={asOf} max={today} disabled={search.isPending}
            onChange={e => setAsOf(e.target.value)}
            className="ml-2 rounded border border-border bg-elevated px-2 py-1" />
        </label>
        <button type="button" disabled={!asOf || search.isPending || !reports.data?.supported}
          onClick={() => search.mutate({ date: asOf, refresh: !!report })}
          className="inline-flex items-center gap-1 rounded-btn bg-accent px-3 py-1 text-white disabled:opacity-40">
          {search.isPending && <Loader2 size={14} className="animate-spin" />}
          {search.isPending ? '正在搜索与整理…' : report ? '重新联网核验' : '联网核验'}
        </button>
        {reports.isPending && <span className="text-xs text-muted">读取已保存报告…</span>}
      </div>
      {reports.data && !reports.data.supported && <p className="text-xs text-amber-500">请在 AI 设置中选择已登录的 Codex CLI。普通文本模型调用不能代替联网搜索。</p>}
      {search.isPending && <p role="status" className="text-xs text-muted">通常需要数分钟，完成后自动保存。收起面板不会重复发起搜索。</p>}
      {error && <p role="alert" className="text-xs text-red-500">{error instanceof Error ? error.message : '核验失败，请重试'}</p>}
      {!report && !reports.isPending && <p className="text-xs text-muted">该截止日暂无核验报告。点击“联网核验”获取资料。</p>}
      <AssessmentSummary symbol={symbol} asOf={asOf} />
      {report && <>
        <p className="text-xs text-muted">{report.name} {report.symbol} · 检索于 {new Date(report.searched_at).toLocaleString()} · 待人工核验</p>
        {report.sections.map(section => <article key={section.topic} className="rounded border border-border p-3 space-y-2">
          <h4 className="font-medium">{section.label}<span className="ml-2 text-xs text-amber-500">{section.status === 'missing' ? '缺少证据' : '已有资料 · 待核验'}</span></h4>
          <p className="text-xs text-secondary whitespace-pre-wrap">{section.summary}</p>
          {section.evidence.map((e, i) => <div key={`${e.url}-${i}`} className="border-l-2 border-border pl-3 text-xs space-y-1">
            <a href={e.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline break-words">{e.title} ↗</a>
            <p className="text-muted">公告日 {e.published_on} · 报告期/事件日期 {e.period || '未明确'}</p>
            <p className="text-secondary whitespace-pre-wrap">模型摘录：{e.excerpt}</p>
          </div>)}
        </article>)}
      </>}
      {!!reports.data?.reports.length && <details className="text-xs text-muted">
        <summary className="cursor-pointer">已保存的核验记录（{reports.data.reports.length}）</summary>
        {Array.from(new Set(reports.data.reports.map(r => r.as_of))).map(day =>
          <button key={day} type="button" disabled={search.isPending} onClick={() => setAsOf(day)} className="mr-3 mt-2 text-accent">{day}</button>)}
      </details>}
    </div>}
  </section>
}

function StockFooter(props: FrontendSlotContextMap[keyof FrontendSlotContextMap]) {
  if (!('symbol' in props)) return null
  const { symbol } = props
  return /^\d{6}\.(SH|SZ|BJ)$/.test(symbol) ? <ResearchPanel key={symbol} symbol={symbol} /> : null
}
const extension: FrontendExtension = {
  id: 'disclosure.research', apiVersion: 1,
  slots: [{ name: 'stock-preview.footer', id: 'disclosure.stock-footer', component: StockFooter }],
}
export default extension
