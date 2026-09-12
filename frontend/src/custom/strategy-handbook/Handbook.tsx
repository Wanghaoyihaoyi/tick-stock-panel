import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Download, Search } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import handbookData from './handbook-data.json'

interface Strategy {
  id: string
  name: string
  category: string
  trigger: string
  exit: string
  risk: string
  improvement: string
  longTermUse: string
  variantId?: string
  variantName?: string
  variantRemoved?: boolean
  backtest?: {
    start: string
    end: string
    baselineReturn: number
    variantReturn: number
    baselineDrawdown: number
    variantDrawdown: number
    baselineTrades: number
    variantTrades: number
  }
  checklist: string[]
}

interface HandbookData {
  asOf: string
  scope: string
  backtestNote: string
  strategies: Strategy[]
  investing: Array<{
    id: string
    title: string
    principle: string
    steps: string[]
    reject: string[]
    dataStatus: string
    sourceTitle: string
    sourceUrl: string
  }>
  sources: Array<{ title: string; url: string }>
  limitations: string[]
}

const data: HandbookData = handbookData
const buttonClass = 'inline-flex items-center justify-center gap-1.5 rounded-btn border border-border bg-surface px-3 py-2 text-xs text-secondary hover:border-accent/50 hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40'
const inputClass = 'w-full rounded-btn border border-border bg-base px-3 py-2 text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent'
const pct = (value: number) => Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '未提供'

function downloadMarkdown(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename.replace(/[^\p{L}\p{N}._-]/gu, '_')}.md`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// 用户记录逐项隔离；未知版本、损坏记录及其他标签页修改均不静默覆盖。
function useLocalRecord<T>(key: string, empty: T, validate: (value: unknown) => value is T) {
  const [initial] = useState(() => {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return { raw, value: empty, error: '' }
      const parsed: unknown = JSON.parse(raw)
      if (!parsed || typeof parsed !== 'object' || !('version' in parsed) || parsed.version !== 1
        || !('value' in parsed) || !validate(parsed.value)) {
        return { raw, value: empty, error: '本地记录版本不兼容或内容损坏，已停止写入以保留原记录。' }
      }
      return { raw, value: parsed.value, error: '' }
    } catch {
      return { raw: null, value: empty, error: '无法读取本地记录，请检查浏览器存储权限；当前内容仍可导出。' }
    }
  })
  const [value, setValue] = useState(initial.value)
  const [error, setError] = useState(initial.error)
  const [saved, setSaved] = useState(Boolean(initial.raw) && !initial.error)
  const previousRaw = useRef(initial.raw)
  function update(next: T) {
    setValue(next)
    setSaved(false)
    if (error) return
    try {
      if (localStorage.getItem(key) !== previousRaw.current) {
        setError('其他标签页已修改本记录。当前输入未覆盖原记录，请先导出，再刷新重新读取。')
        return
      }
      const raw = JSON.stringify({ version: 1, value: next })
      localStorage.setItem(key, raw)
      previousRaw.current = raw
      setSaved(true)
    } catch {
      setError('本地保存失败，当前输入仅在页面内，请先导出备份。')
    }
  }
  return { value, update, error, saved }
}

function StrategyCard({ strategy }: { strategy: Strategy }) {
  const record = useLocalRecord<string[]>(`strategy-handbook:checks:v1:${data.asOf}:${strategy.id}`, [],
    (value): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string' && strategy.checklist.includes(item)))
  const result = strategy.backtest
  const exportCard = () => downloadMarkdown(`${strategy.id}-执行卡-${data.asOf}`, [
    `# ${strategy.name} · 执行卡`, `手册资料日期：${data.asOf}`, `原策略 ID：${strategy.id}`,
    `研究版：${strategy.variantName || '未新增'}（${strategy.variantId || '无'}）`,
    `## 触发条件\n${strategy.trigger}`, `## 退出条件\n${strategy.exit}`, `## 风险\n${strategy.risk}`,
    `## 完善方向\n${strategy.improvement}`, `## 中长期用途\n${strategy.longTermUse}`,
    `## 本地检查记录\n${strategy.checklist.map(item => `- [${record.value.includes(item) ? 'x' : ' '}] ${item}`).join('\n')}`,
    '检查记录不代表策略获批或可以买入。',
    result ? `## 历史回测\n${result.start} 至 ${result.end}\n\n| 指标 | 原策略 | 研究版 |\n|---|---:|---:|\n| 收益 | ${pct(result.baselineReturn)} | ${pct(result.variantReturn)} |\n| 最大回撤 | ${pct(result.baselineDrawdown)} | ${pct(result.variantDrawdown)} |\n| 交易笔数 | ${result.baselineTrades} | ${result.variantTrades} |` : '## 历史回测\n未回测',
    data.backtestNote, strategy.variantRemoved
      ? '## 复测状态\n此研究版因收益恶化已移除，历史数据仅供复盘。原始内置策略仍可查看和回测。'
      : strategy.variantId ? '## 复测步骤\n进入应用回测页 → 候选方案 → 按研究版名称查找 → 载入复测，核对配置再运行。' : '## 复测状态\n暂无独立研究候选。',
    `## 参考资料\n${data.sources.map(source => `- [${source.title}](${source.url})`).join('\n')}`,
  ].join('\n\n'))

  return <details className="group rounded-lg border border-border bg-surface">
    <summary className="cursor-pointer rounded-lg px-4 py-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      <span className="ml-1 font-medium">{strategy.name}</span>
      {strategy.variantName?.startsWith('改善') && <span className="ml-2 text-xs text-accent">改善</span>}
      {strategy.variantRemoved && <span className="ml-2 text-xs text-muted">研究版已移除</span>}
      <span className="ml-3 inline-block rounded bg-elevated px-2 py-0.5 text-xs text-secondary">{strategy.category}</span>
      <span className="mt-1 block pl-5 font-mono text-[11px] text-muted break-all">{strategy.id}</span>
      <span className="mt-2 block pl-5 text-xs leading-relaxed text-secondary">{strategy.improvement}</span>
    </summary>
    <div className="space-y-5 border-t border-border px-4 py-4 text-sm">
      <dl className="grid gap-4 md:grid-cols-2">
        {([['触发条件', strategy.trigger], ['退出条件', strategy.exit], ['风险检查', strategy.risk], ['中长期用途', strategy.longTermUse]] as const).map(([label, text]) =>
          <div key={label}><dt className="mb-1 text-xs font-medium text-muted">{label}</dt><dd className="whitespace-pre-wrap leading-relaxed text-secondary">{text}</dd></div>)}
      </dl>
      <section aria-label={`${strategy.name}回测对照`} className="rounded border border-border bg-base p-3">
        <p className="font-medium">{strategy.variantRemoved ? '原策略与已移除研究版（历史对照）' : '原策略与研究版'}</p>
        <p className="mt-1 break-all text-xs text-muted">{strategy.variantName || '暂无研究版'}{strategy.variantId && ` · ${strategy.variantId}`}</p>
        {result ? <>
          <p className="my-2 text-xs text-muted">{result.start} — {result.end} · 历史样本</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs tabular-nums">
              <caption className="sr-only">{strategy.name}同区间回测对照</caption>
              <thead><tr className="border-b border-border text-muted"><th scope="col" className="py-2 pr-3">指标</th><th scope="col" className="pr-3">原策略</th><th scope="col">研究版</th></tr></thead>
              <tbody>{[
                ['区间收益', pct(result.baselineReturn), pct(result.variantReturn)],
                ['最大回撤', pct(result.baselineDrawdown), pct(result.variantDrawdown)],
                ['交易笔数', result.baselineTrades, result.variantTrades],
              ].map(([label, baseline, variant]) => <tr key={label}><th scope="row" className="py-2 pr-3 font-normal text-secondary">{label}</th><td className="pr-3">{baseline}</td><td>{variant}</td></tr>)}</tbody>
            </table>
          </div>
        </> : <p className="mt-3 text-xs text-muted">未回测</p>}
      </section>
      <fieldset className="space-y-2">
        <legend className="mb-2 font-medium">本地检查记录 <span className="text-xs font-normal text-muted">{record.value.length}/{strategy.checklist.length}</span></legend>
        {strategy.checklist.map(item => <label key={item} className="flex cursor-pointer items-start gap-2 text-secondary">
          <input type="checkbox" checked={record.value.includes(item)} className="mt-1 accent-accent"
            onChange={event => record.update(event.target.checked ? [...record.value, item] : record.value.filter(checked => checked !== item))} />
          <span className="leading-relaxed">{item}</span>
        </label>)}
      </fieldset>
      <p role={record.error ? 'alert' : 'status'} className={`text-xs ${record.error ? 'text-amber-500' : 'text-muted'}`}>
        {record.error || `${record.saved ? '已保存在' : '仅保存在'}本机本浏览器，按策略和手册日期区分；勾选不代表可以买入。`}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} onClick={exportCard}><Download size={14} />导出执行卡</button>
        <Link className={buttonClass} to="/backtest">前往回测 <ArrowUpRight size={14} /></Link>
        <Link className={buttonClass} to="/screener">查看策略筛选 <ArrowUpRight size={14} /></Link>
      </div>
      <p className="text-xs leading-relaxed text-muted">{strategy.variantRemoved
        ? '该研究版及候选已移除，历史结果仅作复盘；上方链接可用于查看原始内置策略。'
        : strategy.variantId ? '回测页点击“候选方案”，按研究版名称查找并载入复测；策略筛选页手动选择相应名称。以上链接不会自动切换策略或下单。' : '此模板没有独立研究候选，使用前须明确因子与评分配方。'}</p>
    </div>
  </details>
}

const researchFields = [
  ['business', '企业与护城河证据', '记录主营业务、竞争优势、证据链接及公告日期。'],
  ['financials', '现金流与负债核验', '记录现金流、利润质量、债务期限、表外负债及所用报告期。'],
  ['valuation', '估值假设与安全边际', '记录保守/基准情景、现金流假设、折现率、估值范围与否定假设的条件。'],
  ['counterevidence', '反证与退出条件', '记录哪些业务或治理变化会推翻判断，避免用价格下跌替代企业分析。'],
  ['reviewDate', '下次复核日期', ''],
] as const
type ResearchField = typeof researchFields[number][0]
type ResearchRecord = Record<ResearchField, string>
const emptyResearch: ResearchRecord = { business: '', financials: '', valuation: '', counterevidence: '', reviewDate: '' }

function ResearchEditor({ symbol }: { symbol: string }) {
  const record = useLocalRecord<ResearchRecord>(`strategy-handbook:company:v1:${symbol}`, emptyResearch,
    (value): value is ResearchRecord => Boolean(value) && typeof value === 'object'
      && researchFields.every(([key]) => key in (value as object) && typeof (value as ResearchRecord)[key] === 'string'))
  const complete = researchFields.every(([key]) => record.value[key].trim())
  return <div className="mt-4 space-y-4 border-t border-border pt-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="font-medium">{symbol} · 本地研究记录</h3>
      <span className="text-xs text-muted">{complete ? '记录已填写，需人工判断' : '研究待补全'}</span>
    </div>
    {researchFields.map(([key, label, placeholder]) => <label key={key} className="block text-xs font-medium text-secondary">
      {label}
      {key === 'reviewDate'
        ? <input type="date" className={`${inputClass} mt-2 sm:max-w-xs`} value={record.value[key]} onChange={event => record.update({ ...record.value, [key]: event.target.value })} />
        : <textarea rows={3} className={`${inputClass} mt-2 resize-y font-normal leading-relaxed`} placeholder={placeholder} value={record.value[key]} onChange={event => record.update({ ...record.value, [key]: event.target.value })} />}
    </label>)}
    <p role={record.error ? 'alert' : 'status'} className={`text-xs ${record.error ? 'text-amber-500' : 'text-muted'}`}>
      {record.error || (record.saved ? '已自动保存到本机本浏览器。清理浏览器数据会删除记录，请及时导出。' : '填写后自动保存到本机本浏览器。')}
    </p>
    <button type="button" className={buttonClass} onClick={() => downloadMarkdown(`${symbol}-中长期研究`, [
      `# ${symbol} · 中长期研究记录`, `导出日期：${new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())}`,
      complete ? '记录已填写，需人工判断。' : '研究待补全。',
      ...researchFields.map(([key, label]) => `## ${label}\n${record.value[key] || '待补全'}`),
      '本记录由用户填写，仅作人工研究，不构成自动买入或交易批准。',
      `## 手册参考资料\n${data.sources.map(source => `- [${source.title}](${source.url})`).join('\n')}`,
    ].join('\n\n'))}><Download size={14} />导出研究记录</button>
  </div>
}

function Investing() {
  const [symbolInput, setSymbolInput] = useState('')
  const [symbol, setSymbol] = useState('')
  const [error, setError] = useState('')
  return <div className="space-y-4">
    <p className="text-sm leading-relaxed text-secondary">中长期研究按企业分别记录：理解业务、核对事实、估值，再决定是否继续观察。以下是人工研究流程，不会生成买入信号或自动交易。</p>
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="font-medium">企业研究记录</h2>
      <p className="mt-2 text-xs leading-relaxed text-muted">与短线检查记录分别保存。输入同一股票代码可重新打开；数据仅在本机本浏览器，不会同步到服务器。</p>
      <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={event => {
        event.preventDefault()
        const next = symbolInput.trim().toUpperCase()
        if (!/^\d{6}\.(SH|SZ|BJ)$/.test(next)) { setError('请输入完整股票代码，例如 600000.SH、000001.SZ 或 920001.BJ。'); return }
        setSymbol(next)
        setError('')
      }}>
        <label className="flex-1 text-xs text-secondary sm:max-w-xs">股票代码
          <input className={`${inputClass} mt-1`} value={symbolInput} onChange={event => setSymbolInput(event.target.value)} placeholder="例如 600000.SH" autoCapitalize="characters" />
        </label>
        <button type="submit" className={buttonClass}>打开 / 新建记录</button>
        <Link to="/financials" className={buttonClass}>查看财务数据 <ArrowUpRight size={14} /></Link>
      </form>
      {error && <p role="alert" className="mt-2 text-xs text-amber-500">{error}</p>}
      {symbol && <ResearchEditor key={symbol} symbol={symbol} />}
    </section>
    <div className="grid gap-4 xl:grid-cols-2">
      {data.investing.map(item => <article key={item.id} className="rounded-lg border border-border bg-surface p-4 text-sm">
        <h2 className="font-medium">{item.title}</h2>
        <p className="mt-2 leading-relaxed text-secondary">{item.principle}</p>
        <h3 className="mb-2 mt-4 text-xs font-medium text-muted">研究步骤</h3>
        <ol className="list-decimal space-y-2 pl-5 text-secondary">{item.steps.map(step => <li key={step}>{step}</li>)}</ol>
        <h3 className="mb-2 mt-4 text-xs font-medium text-muted">否决 / 暂缓条件</h3>
        <ul className="list-disc space-y-2 pl-5 text-secondary">{item.reject.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <p className="mt-4 rounded bg-elevated p-3 text-xs leading-relaxed text-secondary">{item.dataStatus}</p>
        <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs text-accent hover:underline">{item.sourceTitle} ↗</a>
      </article>)}
    </div>
  </div>
}

export default function Handbook() {
  const [tab, setTab] = useState<'trading' | 'investing'>('trading')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const categories = [...new Set(data.strategies.map(strategy => strategy.category))]
  const needle = search.trim().toLowerCase()
  const filtered = data.strategies.filter(strategy => (category === 'all' || strategy.category === category)
    && [strategy.name, strategy.id, strategy.variantName, strategy.variantId].some(text => text?.toLowerCase().includes(needle)))
  return <div className="min-h-full bg-base">
    <PageHeader title="策略手册" subtitle={<span className="hidden sm:inline">短线执行与中长期研究分别管理</span>} />
    <main className="mx-auto max-w-6xl space-y-5 px-3 py-4 sm:px-5">
      <header className="space-y-2">
        <p className="text-xs text-muted">资料日期 {data.asOf} · {data.strategies.length} 个内置策略</p>
        <p className="text-sm leading-relaxed text-secondary">{data.scope}</p>
      </header>
      <nav aria-label="策略手册分类" className="flex gap-2 border-b border-border pb-3">
        {([['trading', '短线策略'], ['investing', '中长期研究']] as const).map(([id, label]) => <button key={id} type="button" aria-pressed={tab === id} onClick={() => setTab(id)}
          className={`${buttonClass} ${tab === id ? 'border-accent/60 bg-accent/10 text-accent' : ''}`}>{label}</button>)}
      </nav>
      {tab === 'trading' ? <section className="space-y-4" aria-label="短线策略">
        <div className="flex flex-wrap gap-3">
          <label className="relative min-w-0 flex-1 basis-52"><span className="sr-only">搜索策略名称或 ID</span><Search size={15} className="absolute left-3 top-3 text-muted" />
            <input type="search" className={`${inputClass} pl-9`} placeholder="搜索策略名称或 ID" value={search} onChange={event => setSearch(event.target.value)} />
          </label>
          <label className="flex min-w-0 items-center gap-2 whitespace-nowrap text-xs text-secondary">分类
            <select className={inputClass} value={category} onChange={event => setCategory(event.target.value)}><option value="all">全部分类</option>{categories.map(item => <option key={item} value={item}>{item}</option>)}</select>
          </label>
        </div>
        <details className="rounded border border-border bg-surface p-3 text-xs text-secondary">
          <summary className="cursor-pointer font-medium">回测口径与阅读方法</summary><p className="mt-2 whitespace-pre-wrap leading-relaxed">{data.backtestNote}</p>
        </details>
        <p role="status" className="text-xs text-muted">显示 {filtered.length} / {data.strategies.length} 个策略 · 展开查看执行条件、风险与回测</p>
        {filtered.length ? filtered.map(strategy => <StrategyCard key={`${data.asOf}:${strategy.id}`} strategy={strategy} />)
          : <div className="rounded border border-dashed border-border p-8 text-center text-sm text-muted">没有匹配的策略。<button className="ml-2 text-accent hover:underline" type="button" onClick={() => { setSearch(''); setCategory('all') }}>清除筛选</button></div>}
      </section> : <Investing />}
      <footer className="space-y-3 border-t border-border pt-4 text-xs leading-relaxed text-muted">
        <details><summary className="cursor-pointer font-medium">适用边界与资料来源</summary>
          <ul className="my-3 list-disc space-y-1 pl-5">{data.limitations.map(item => <li key={item}>{item}</li>)}</ul>
          <ul className="space-y-1">{data.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">{source.title} ↗</a></li>)}</ul>
        </details>
      </footer>
    </main>
  </div>
}
