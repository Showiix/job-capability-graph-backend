import { useEffect, useState, type CSSProperties } from 'react'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  FallOutlined,
  RiseOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'
import { listEvolution, type EvolutionItem, type EvolutionPage } from '../services/evolutionApi'
import EmergingJobsView from './EmergingJobsView'
import FadeContent from '../components/reactbits/FadeContent/FadeContent'
import CountUp from '../components/reactbits/CountUp/CountUp'

const changeTypes = ['技能新增', 'AI技能新增', '技能衰退', '技能权重上升', '技能权重下降', '升级（加分→必备）', '降级（必备→加分）', '过时技能淘汰']

const CHANGE_TONES: Record<string, string> = {
  技能新增: 'tone-rise',
  AI技能新增: 'tone-rise',
  技能衰退: 'tone-fall',
  过时技能淘汰: 'tone-fall',
  技能权重上升: 'tone-up',
  '升级（加分→必备）': 'tone-up',
  技能权重下降: 'tone-down',
  '降级（必备→加分）': 'tone-down',
}

function changeTone(value: string) {
  return CHANGE_TONES[value] ?? 'tone-rise'
}

const TONE_ICONS: Record<string, typeof RiseOutlined> = {
  'tone-rise': RiseOutlined,
  'tone-fall': FallOutlined,
  'tone-up': ArrowUpOutlined,
  'tone-down': ArrowDownOutlined,
}

function changeIcon(value: string) {
  const Icon = TONE_ICONS[changeTone(value)] ?? RiseOutlined
  return <Icon />
}

type EvolutionMode = 'emerging' | 'all'

const EVOLUTION_MODES: { id: EvolutionMode; index: string; label: string; coord: string; desc: string }[] = [
  {
    id: 'emerging',
    index: '01',
    label: '新兴岗位',
    coord: 'MARKET RADAR',
    desc: '基于岗位定义、JD 覆盖、行业场景和技术词，查看待审核的新岗位候选。',
  },
  {
    id: 'all',
    index: '02',
    label: '全岗位',
    coord: 'FULL CATALOG',
    desc: '查看全部岗位的技能新增、衰退、权重和必备等级变化，并追溯 JD 证据。',
  },
]

function EvolutionWorkspace() {
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
  const stats = [
    { label: '变化候选', value: data?.statistics.total_changes ?? 0 },
    { label: '覆盖岗位', value: data?.statistics.total_jobs_with_changes ?? 0 },
    { label: '高置信度', value: data?.statistics.high_confidence ?? 0 },
  ]

  return (
    <>
      <div className="emerging-stats mb-6">
        {stats.map((stat) => (
          <div key={stat.label} className="metric-card archive-metric emerging-stat" style={{ '--accent': '#ee1212' } as CSSProperties}>
            <div className="metric-card__label">{stat.label}</div>
            <div className="metric-card__value">
              <CountUp to={stat.value} separator="," duration={1.6} />
            </div>
          </div>
        ))}
      </div>

      {error && <div className="archive-panel glass p-4 mb-5 text-sm text-red-300">{error}</div>}

      <FadeContent duration={650} threshold={0.05}>
        <div className="evolution-filter-bar archive-panel glass p-4 mb-5">
          <FrameCorners />
          <label className="evolution-filter-field evolution-filter-field--grow">
            <span><SearchOutlined /> 检索</span>
            <input
              className="archive-control"
              value={query}
              onChange={(event) => { setQuery(event.target.value); setPage(1) }}
              placeholder="搜索岗位或能力"
            />
          </label>
          <label className="evolution-filter-field">
            <span>变化类型</span>
            <select className="archive-control" value={changeType} onChange={(event) => { setChangeType(event.target.value); setPage(1) }}>
              <option value="">全部变化</option>
              {changeTypes.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="evolution-filter-field">
            <span>置信度</span>
            <select className="archive-control" value={confidence} onChange={(event) => { setConfidence(event.target.value); setPage(1) }}>
              <option value="">全部置信度</option>
              <option value="高">高</option>
              <option value="中">中</option>
              <option value="低">低</option>
            </select>
          </label>
        </div>
      </FadeContent>

      <div className="evolution-workspace">
        <FadeContent duration={750} delay={0.12} threshold={0.05}>
          <section className="archive-panel glass evolution-queue">
            <FrameCorners />
            <header className="evolution-panel-head">
              <span className="evolution-panel-head__kicker">Change queue</span>
              <h2>变化队列</h2>
              <strong><CountUp to={data?.total ?? 0} separator="," duration={1.6} /> 条候选</strong>
            </header>
          <div className="evolution-queue__list">
            {data?.items.map((item, index) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSelected(item)}
                className={`archive-row evolution-row ${changeTone(item.change_type)} ${selected?.id === item.id ? 'is-selected' : ''}`}
              >
                <span className="evolution-row__index">{String((page - 1) * 20 + index + 1).padStart(3, '0')}</span>
                <span className="evolution-row__body">
                  <strong>{item.job_name}</strong>
                  <span className="evolution-row__skill">{item.skill}</span>
                  <span className="evolution-row__meta">
                    <span className={`tag evolution-row__type ${changeTone(item.change_type)}`}>{item.change_type}</span>
                    <small>置信度 {item.confidence} · 效应量 {item.effect_size}</small>
                  </span>
                </span>
              </button>
            ))}
            {data && data.items.length === 0 && <div className="evolution-empty">没有符合条件的变化记录。</div>}
          </div>
          <footer className="evolution-queue__pager">
            <button type="button" className="btn btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
            <span>{page} / {totalPages}</span>
            <button type="button" className="btn btn-ghost" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</button>
          </footer>
          </section>
        </FadeContent>

        <FadeContent duration={750} delay={0.26} threshold={0.05}>
          <section className="archive-panel glass evolution-detail">
          <FrameCorners />
          {selected ? (
            <>
              <header className={`evolution-panel-head evolution-hero ${changeTone(selected.change_type)}`}>
                <span className="evolution-panel-head__kicker">Evidence review / {selected.change_type}</span>
                <h2>{selected.job_name}</h2>
                <p className="evolution-hero__skill">{selected.skill}</p>
              </header>
              <div className="flex gap-2 flex-wrap">
                <span className={`tag evolution-row__type ${changeTone(selected.change_type)}`}>{changeIcon(selected.change_type)}{selected.change_type}</span>
                <span className="tag tag-blue">置信度 {selected.confidence}</span>
              </div>
              <p className="evolution-detail__desc">{selected.trend_description || selected.update_summary || '暂无趋势说明'}</p>
              <div className="evolution-detail__grid">
                <div className="evolution-detail__cell">
                  <span><DatabaseOutlined /> JD 证据</span>
                  <strong>{(selected.evidence.jd_count ?? 0).toLocaleString('zh-CN')}</strong>
                  <small>{Object.keys(selected.evidence.sources ?? {}).join(' / ') || '来源未标注'}</small>
                </div>
                <div className="evolution-detail__cell">
                  <span><SafetyCertificateOutlined /> 统计控制</span>
                  <strong>{selected.effect_size}</strong>
                  <small>Cohen's h / effect size</small>
                </div>
              </div>
              <div className="evolution-detail__section">
                <span className="evolution-panel-head__kicker">Evidence samples</span>
                <h3>证据样例</h3>
                <div className="evolution-samples">
                  {(selected.evidence.samples ?? []).slice(0, 5).map((sample, index) => (
                    <article key={`${sample.company}-${index}`} className="evolution-sample">
                      <div className="evolution-sample__meta">
                        <strong>{sample.company || '未知企业'}</strong>
                        <span>{sample.source} · {sample.issue_date}</span>
                      </div>
                      <p>{sample.snippet}</p>
                    </article>
                  ))}
                  {(selected.evidence.samples ?? []).length === 0 && <div className="evolution-empty">暂无证据样例。</div>}
                </div>
              </div>
              <details className="evolution-controls">
                <summary><BarChartOutlined /> 查看四重控制详情</summary>
                <pre>{JSON.stringify(selected.controls, null, 2)}</pre>
              </details>
            </>
          ) : (
            <div className="evolution-empty evolution-empty--detail">请选择一条能力变化。</div>
          )}
          </section>
        </FadeContent>
      </div>
    </>
  )
}

export default function CapabilityEvolutionPage() {
  const [mode, setMode] = useState<EvolutionMode>('emerging')
  const activeMode = EVOLUTION_MODES.find((item) => item.id === mode) ?? EVOLUTION_MODES[0]

  return (
    <div className="page-shell page-shell--emerging min-h-screen pt-14">
      <div className="page-shell__inner max-w-7xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive">
          <FrameCorners />
          <div className="page-head__icon"><RiseOutlined /></div>
          <div className="page-head__copy">
            <div className="page-head__eyebrow">Capability evolution / evidence review</div>
            <h1 className="page-head__title">岗位能力动态演化</h1>
            <p className="page-head__desc">{activeMode.desc}</p>
          </div>
        </div>

        <div className="evolution-mode-switch" role="tablist" aria-label="切换岗位范围">
          {EVOLUTION_MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={mode === item.id}
              className={`evolution-mode-switch__option ${mode === item.id ? 'is-active' : ''}`}
              onClick={() => setMode(item.id)}
            >
              <span className="evolution-mode-switch__index">{item.index}</span>
              <span className="evolution-mode-switch__copy">
                <strong>{item.label}</strong>
                <em>{item.coord}</em>
              </span>
            </button>
          ))}
        </div>

        {mode === 'emerging' ? <EmergingJobsView /> : <EvolutionWorkspace />}
      </div>
    </div>
  )
}
