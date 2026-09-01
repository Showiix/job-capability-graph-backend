import { useEffect, useState } from 'react'
import { BarChartOutlined, DatabaseOutlined, RiseOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'
import { listEvolution, type EvolutionItem, type EvolutionPage } from '../services/evolutionApi'

const changeTypes = ['技能新增', 'AI技能新增', '技能衰退', '技能权重上升', '技能权重下降', '升级（加分→必备）', '降级（必备→加分）', '过时技能淘汰']

export default function CapabilityEvolutionPage() {
  const [data, setData] = useState<EvolutionPage | null>(null)
  const [selected, setSelected] = useState<EvolutionItem | null>(null)
  const [query, setQuery] = useState('')
  const [changeType, setChangeType] = useState('')
  const [confidence, setConfidence] = useState('')
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    listEvolution({ query: query || undefined, change_type: changeType || undefined, confidence: confidence || undefined, page, page_size: 20 })
      .then((value) => {
        if (!alive) return
        setData(value)
        setSelected((current) => value.items.find((item) => item.id === current?.id) ?? value.items[0] ?? null)
        setError('')
      })
      .catch((reason) => alive && setError(reason.apiMessage ?? reason.message ?? '能力演化数据读取失败'))
    return () => { alive = false }
  }, [changeType, confidence, page, query])

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / 20))
  return (
    <div className="page-shell page-shell--emerging min-h-screen pt-14">
      <div className="page-shell__inner max-w-7xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive"><FrameCorners /><div className="page-head__icon"><RiseOutlined /></div><div className="page-head__copy"><div className="page-head__eyebrow">Capability evolution / evidence review</div><h1 className="page-head__title">岗位能力动态演化</h1><p className="page-head__desc">查看 524 个岗位的 4007 条技能新增、衰退、权重和必备等级变化，并追溯 JD 证据。</p></div></div>
        <div className="emerging-stats mb-8"><div className="metric-card archive-metric emerging-stat emerging-stat--primary"><div className="metric-card__label">变化候选</div><div className="metric-card__value">{data?.statistics.total_changes ?? 4007}</div></div><div className="metric-card archive-metric emerging-stat"><div className="metric-card__label">覆盖岗位</div><div className="metric-card__value">{data?.statistics.total_jobs_with_changes ?? 524}</div></div><div className="metric-card archive-metric emerging-stat"><div className="metric-card__label">高置信度</div><div className="metric-card__value">{data?.statistics.high_confidence ?? 1415}</div></div></div>
        <div className="archive-panel glass p-4 mb-5 flex gap-3 flex-wrap"><input className="archive-control flex-1 min-w-56 px-3" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="搜索岗位或能力" /><select className="archive-control px-3" value={changeType} onChange={(event) => { setChangeType(event.target.value); setPage(1) }}><option value="">全部变化</option>{changeTypes.map((value) => <option key={value} value={value}>{value}</option>)}</select><select className="archive-control px-3" value={confidence} onChange={(event) => { setConfidence(event.target.value); setPage(1) }}><option value="">全部置信度</option><option value="高">高</option><option value="中">中</option><option value="低">低</option></select></div>
        {error && <div className="border border-red-700 p-3 text-red-300 mb-4">{error}</div>}
        <div className="grid lg:grid-cols-[360px_1fr] gap-5"><section className="archive-panel glass p-3"><FrameCorners /><div className="font-bold mb-3">变化队列 · {data?.total ?? 0}</div><div className="max-h-[620px] overflow-y-auto space-y-1">{data?.items.map((item) => <button key={item.id} type="button" onClick={() => setSelected(item)} className={`w-full text-left border-l-2 p-3 ${selected?.id === item.id ? 'border-[#ee1212] bg-white/5' : 'border-transparent'}`}><strong>{item.job_name}</strong><div className="text-sm text-[#e4b592]">{item.skill} · {item.change_type}</div><small className="text-[var(--text-dim)]">置信度 {item.confidence} · 效应量 {item.effect_size}</small></button>)}</div><div className="flex justify-between items-center mt-4"><button className="btn btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>{page} / {totalPages}</span><button className="btn btn-ghost" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</button></div></section><section className="archive-panel glass p-6"><FrameCorners />{selected ? <><h2 className="text-xl font-bold">{selected.job_name} · {selected.skill}</h2><div className="flex gap-2 mt-2"><span className="tag tag-orange"><RiseOutlined />{selected.change_type}</span><span className="tag tag-blue">置信度 {selected.confidence}</span></div><p className="mt-5 text-sm leading-6 text-[var(--text-dim)]">{selected.trend_description || selected.update_summary || '暂无趋势说明'}</p><div className="grid sm:grid-cols-2 gap-3 mt-5"><div className="border border-[var(--border)] p-4"><div className="text-xs text-[#e4b592]"><DatabaseOutlined /> JD 证据</div><strong className="text-2xl">{selected.evidence.jd_count ?? 0}</strong><div className="text-xs text-[var(--text-dim)]">{Object.keys(selected.evidence.sources ?? {}).join(' / ') || '来源未标注'}</div></div><div className="border border-[var(--border)] p-4"><div className="text-xs text-[#e4b592]"><SafetyCertificateOutlined /> 统计控制</div><strong className="text-2xl">{selected.effect_size}</strong><div className="text-xs text-[var(--text-dim)]">Cohen's h / effect size</div></div></div><h3 className="font-bold mt-6 mb-3">证据样例</h3><div className="space-y-2">{(selected.evidence.samples ?? []).slice(0, 5).map((sample, index) => <article key={`${sample.company}-${index}`} className="border border-[var(--border)] p-3"><div className="text-xs text-[#e4b592]">{sample.company || '未知企业'} · {sample.source} · {sample.issue_date}</div><p className="mt-1 text-sm text-[var(--text-dim)]">{sample.snippet}</p></article>)}</div><details className="mt-5"><summary className="cursor-pointer text-sm"><BarChartOutlined /> 查看四重控制详情</summary><pre className="mt-2 overflow-auto bg-black/40 p-3 text-xs">{JSON.stringify(selected.controls, null, 2)}</pre></details></> : <div className="text-[var(--text-dim)]">请选择一条能力变化。</div>}</section></div>
      </div>
    </div>
  )
}
