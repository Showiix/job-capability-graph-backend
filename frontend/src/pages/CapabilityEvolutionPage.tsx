import { useEffect, useState } from 'react'
import { Input, Select, Tag, Alert, Pagination } from 'antd'
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

  return (
    <div className="page-shell page-shell--emerging min-h-screen pt-14">
      <div className="page-shell__inner max-w-7xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive"><FrameCorners /><div className="page-head__icon"><RiseOutlined /></div><div className="page-head__copy"><div className="page-head__eyebrow">Capability evolution / evidence review</div><h1 className="page-head__title">岗位能力动态演化</h1><p className="page-head__desc">查看 524 个岗位的 4007 条技能新增、衰退、权重和必备等级变化，并追溯 JD 证据。</p></div></div>
        <div className="emerging-stats mb-8"><div className="metric-card archive-metric emerging-stat emerging-stat--primary"><div className="metric-card__label">变化候选</div><div className="metric-card__value">{data?.statistics.total_changes ?? 4007}</div></div><div className="metric-card archive-metric emerging-stat"><div className="metric-card__label">覆盖岗位</div><div className="metric-card__value">{data?.statistics.total_jobs_with_changes ?? 524}</div></div><div className="metric-card archive-metric emerging-stat"><div className="metric-card__label">高置信度</div><div className="metric-card__value">{data?.statistics.high_confidence ?? 1415}</div></div></div>
        <div className="archive-panel glass p-5 mb-5 flex gap-3 flex-wrap items-center"><Input className="flex-1 min-w-56" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="搜索岗位或能力" allowClear /><Select className="w-52" value={changeType || undefined} onChange={(value) => { setChangeType(value ?? ''); setPage(1) }} allowClear placeholder="全部变化" options={changeTypes.map((value) => ({ value, label: value }))} /><Select className="w-36" value={confidence || undefined} onChange={(value) => { setConfidence(value ?? ''); setPage(1) }} allowClear placeholder="全部置信度" options={['高', '中', '低'].map((value) => ({ value, label: value }))} /></div>
        {error && <Alert className="mb-4" type="error" showIcon message={error} />}
        <div className="grid lg:grid-cols-[380px_1fr] gap-5"><section className="archive-panel glass p-4"><FrameCorners /><div className="font-bold text-base mb-3">变化队列 · {data?.total ?? 0}</div><div className="max-h-[620px] overflow-y-auto flex flex-col gap-1">{data?.items.map((item) => <button key={item.id} type="button" onClick={() => setSelected(item)} className={`w-full text-left border-l-2 p-4 ${selected?.id === item.id ? 'border-[#ee1212] bg-white/5' : 'border-transparent'}`}><strong className="text-[15px]">{item.job_name}</strong><div className="mt-1 text-sm text-[#e4b592]">{item.skill} · {item.change_type}</div><small className="mt-1 block text-[13px] text-[var(--text-dim)]">置信度 {item.confidence} · 效应量 {item.effect_size}</small></button>)}</div><Pagination className="mt-4" current={page} pageSize={20} total={data?.total ?? 0} showSizeChanger={false} onChange={setPage} /></section><section className="archive-panel glass p-6"><FrameCorners />{selected ? <><h2 className="text-xl font-bold">{selected.job_name} · {selected.skill}</h2><div className="flex gap-2 mt-3"><Tag color="orange">{selected.change_type}</Tag><Tag color="blue">置信度 {selected.confidence}</Tag></div><p className="mt-5 text-sm leading-7 text-[var(--text-dim)]">{selected.trend_description || selected.update_summary || '暂无趋势说明'}</p><div className="grid sm:grid-cols-2 gap-3 mt-5"><div className="border border-[var(--border)] p-4"><div className="text-sm text-[#e4b592]"><DatabaseOutlined /> JD 证据</div><strong className="text-3xl tabular-nums">{selected.evidence.jd_count ?? 0}</strong><div className="text-sm text-[var(--text-dim)]">{Object.keys(selected.evidence.sources ?? {}).join(' / ') || '来源未标注'}</div></div><div className="border border-[var(--border)] p-4"><div className="text-sm text-[#e4b592]"><SafetyCertificateOutlined /> 统计控制</div><strong className="text-3xl tabular-nums">{selected.effect_size}</strong><div className="text-sm text-[var(--text-dim)]">Cohen's h / effect size</div></div></div><h3 className="font-bold text-base mt-6 mb-3">证据样例</h3><div className="flex flex-col gap-2">{(selected.evidence.samples ?? []).slice(0, 5).map((sample, index) => <article key={`${sample.company}-${index}`} className="border border-[var(--border)] p-4"><div className="text-sm text-[#e4b592]">{sample.company || '未知企业'} · {sample.source} · {sample.issue_date}</div><p className="mt-1 text-sm leading-6 text-[var(--text-dim)]">{sample.snippet}</p></article>)}</div><details className="mt-5"><summary className="cursor-pointer text-sm"><BarChartOutlined /> 查看四重控制详情</summary><pre className="mt-2 overflow-auto bg-black/40 p-3 text-xs">{JSON.stringify(selected.controls, null, 2)}</pre></details></> : <div className="text-[var(--text-dim)]">请选择一条能力变化。</div>}</section></div>
      </div>
    </div>
  )
}
