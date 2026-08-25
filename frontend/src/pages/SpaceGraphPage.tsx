import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  ExclamationCircleOutlined,
  FilterOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { GraphScene3D } from '../components/GraphScene3D'
import { FrameCorners } from '../components/FrameCorners'
import { fetchGraphData } from '../services/graphApi'
import type { GraphData, Planet, Star } from '../types/graph'
import { findGraphStarForRole } from '../utils/graphRoleMatch'

const typeColor: Record<string, string> = {
  core: '#ee1212',
  foundation: '#dad0c8',
  frontier: '#e4b592',
}

const typeLabel: Record<string, string> = {
  core: '核心技能',
  foundation: '基础技能',
  frontier: '前沿技能',
}

const FEATURED_LIMIT = 8
const AUTO_HIDE_LABEL_LIMIT = 48
const AUTO_HIDE_SKILL_LABEL_LIMIT = 320

export default function SpaceGraphPage() {
  const [searchParams] = useSearchParams()
  const [graphData, setGraphData] = useState<GraphData>({ stars: [], planets: [], metadata: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedStar, setSelectedStar] = useState<Star | null>(null)
  const [selectedPlanet, setSelectedPlanet] = useState<Planet | null>(null)
  const [filterTypes, setFilterTypes] = useState<string[]>(['core', 'foundation', 'frontier'])
  const [showJobLabels, setShowJobLabels] = useState(true)
  const [showSkillLabels, setShowSkillLabels] = useState(true)
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [jobPickerOpen, setJobPickerOpen] = useState(false)
  const [routeJobApplied, setRouteJobApplied] = useState(false)
  const routeJobName = searchParams.get('job') ?? ''
  const routeJobId = searchParams.get('jobId') ?? ''

  useEffect(() => {
    async function loadGraphData() {
      try {
        setLoading(true)
        setError(null)
        const data = await fetchGraphData()
        setGraphData(data)
      } catch (err) {
        console.error('Failed to load graph data:', err)
        setError('图谱数据读取失败，请检查后端服务')
      } finally {
        setLoading(false)
      }
    }

    loadGraphData()
  }, [])

  useEffect(() => {
    setRouteJobApplied(false)
  }, [routeJobId, routeJobName])

  const featuredStarIds = graphData.metadata?.featured_star_ids ?? []
  const featuredStars = useMemo(() => {
    const preferred = featuredStarIds
      .map((id) => graphData.stars.find((star) => star.id === id))
      .filter(Boolean) as Star[]

    if (preferred.length > 0) {
      const fallback = graphData.stars.filter((star) => !preferred.some((item) => item.id === star.id))
      return [...preferred, ...fallback].slice(0, FEATURED_LIMIT)
    }

    return graphData.stars
      .filter((star) => star.isEmerging)
      .sort((a, b) => (b.sources ?? 0) - (a.sources ?? 0))
      .slice(0, FEATURED_LIMIT)
  }, [featuredStarIds, graphData.stars])

  const searchResults = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return graphData.stars

    return graphData.stars.filter((star) => {
      const haystack = [
        star.label,
        star.domain,
        star.requiredSkills.join(' '),
        star.bonusSkills.join(' '),
        star.sampleJobs?.map((job) => `${job.jobName} ${job.companyName} ${job.city}`).join(' '),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [graphData.stars, searchQuery])

  const selectedJobIdSet = useMemo(() => new Set(selectedJobIds), [selectedJobIds])
  const candidateStars = searchQuery.trim() ? searchResults : graphData.stars
  const visibleStars = useMemo(() => {
    if (selectedJobIds.length > 0) {
      return graphData.stars.filter((star) => selectedJobIdSet.has(star.id))
    }
    if (searchQuery.trim()) return searchResults
    return featuredStars.length > 0 ? featuredStars : graphData.stars.slice(0, FEATURED_LIMIT)
  }, [featuredStars, graphData.stars, searchQuery, searchResults, selectedJobIdSet, selectedJobIds.length])

  const visibleStarIds = useMemo(() => new Set(visibleStars.map((star) => star.id)), [visibleStars])
  const visiblePlanets = useMemo(
    () =>
      graphData.planets.filter(
        (planet) => filterTypes.includes(planet.type) && visibleStarIds.has(planet.starId),
      ),
    [filterTypes, graphData.planets, visibleStarIds],
  )

  useEffect(() => {
    if (selectedStar && !visibleStarIds.has(selectedStar.id)) {
      setSelectedStar(null)
    }
    if (selectedPlanet && !visibleStarIds.has(selectedPlanet.starId)) {
      setSelectedPlanet(null)
    }
  }, [selectedPlanet, selectedStar, visibleStarIds])

  const selectedJobs = useMemo(
    () => graphData.stars.filter((star) => selectedJobIdSet.has(star.id)),
    [graphData.stars, selectedJobIdSet],
  )

  const totalJobs = graphData.metadata?.total_jobs ?? graphData.stars.reduce((sum, star) => sum + (star.jobCount ?? star.sources ?? 0), 0)
  const totalCategories = graphData.metadata?.total_categories ?? graphData.stars.length
  const sourceCounts = graphData.metadata?.source_counts ?? {}
  const sourceSummary = Object.entries(sourceCounts)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)

  const isAllSelected = selectedJobIds.length > 0 && selectedJobIds.length === graphData.stars.length
  const jobSelectionLabel = isAllSelected
    ? '全量岗位'
    : selectedJobIds.length > 0
      ? `${selectedJobIds.length} 个岗位`
      : searchQuery.trim()
        ? `${searchResults.length} 个搜索结果`
        : `热门新兴 ${Math.min(FEATURED_LIMIT, featuredStars.length || graphData.stars.length)}`

  const currentViewLabel = isAllSelected
    ? '全量岗位星系'
    : selectedJobIds.length > 0
      ? `已筛选 ${selectedJobIds.length} 个岗位`
      : searchQuery.trim()
        ? `搜索命中 ${visibleStars.length} 个岗位`
        : '默认热门新兴岗位'

  const planetStar = selectedPlanet ? graphData.stars.find((star) => star.id === selectedPlanet.starId) : null
  const effectiveShowJobLabels = showJobLabels && visibleStars.length <= AUTO_HIDE_LABEL_LIMIT
  const effectiveShowSkillLabels = showSkillLabels && visiblePlanets.length <= AUTO_HIDE_SKILL_LABEL_LIMIT

  const closeDetail = () => {
    setSelectedStar(null)
    setSelectedPlanet(null)
  }

  const toggleFilterType = (type: string) => {
    setFilterTypes((prev) => (prev.includes(type) ? prev.filter((item) => item !== type) : [...prev, type]))
  }

  const toggleJobSelection = (jobId: string) => {
    setSelectedJobIds((prev) => (
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [...prev, jobId]
    ))
  }

  const showFeaturedView = () => {
    setSelectedJobIds([])
    setSearchQuery('')
    closeDetail()
  }

  const selectAllJobs = () => {
    setSelectedJobIds(graphData.stars.map((star) => star.id))
    closeDetail()
  }

  const selectVisibleCandidates = () => {
    setSelectedJobIds(candidateStars.map((star) => star.id))
    closeDetail()
  }

  const clearJobSelection = () => {
    setSelectedJobIds([])
    closeDetail()
  }

  const handleStarClick = (star: Star) => {
    setSelectedStar(star)
    setSelectedPlanet(null)
  }

  const handlePlanetClick = (planet: Planet) => {
    setSelectedPlanet(planet)
    setSelectedStar(null)
  }

  useEffect(() => {
    if (routeJobApplied || loading || (!routeJobName && !routeJobId)) return

    const routeStar = findGraphStarForRole(graphData.stars, {
      jobRoleId: routeJobId,
      roleId: routeJobId,
      canonicalName: routeJobName,
    })

    if (routeStar) {
      setSelectedJobIds([routeStar.id])
      setSelectedStar(routeStar)
      setSelectedPlanet(null)
      setSearchQuery('')
    } else if (routeJobName) {
      setSelectedJobIds([])
      setSelectedStar(null)
      setSelectedPlanet(null)
      setSearchQuery(routeJobName)
    }

    setRouteJobApplied(true)
  }, [graphData.stars, loading, routeJobApplied, routeJobId, routeJobName])

  const renderJobPicker = () => (
    <div className="graph-job-picker">
      <button
        type="button"
        className={`graph-job-picker__trigger archive-control ${jobPickerOpen ? 'is-open' : ''}`}
        onClick={() => setJobPickerOpen((value) => !value)}
      >
        <FilterOutlined />
        <span>岗位筛选</span>
        <strong>{jobSelectionLabel}</strong>
        <DownOutlined />
      </button>

      {jobPickerOpen && (
        <div className="graph-job-picker__menu archive-panel glass">
          <FrameCorners />
          <div className="graph-job-picker__actions">
            <button type="button" onClick={showFeaturedView}>热门默认</button>
            <button type="button" onClick={selectAllJobs}>全量岗位</button>
            <button type="button" onClick={selectVisibleCandidates} disabled={candidateStars.length === 0}>
              全选结果
            </button>
            <button type="button" onClick={clearJobSelection} disabled={selectedJobIds.length === 0}>
              清空选择
            </button>
          </div>

          <div className="graph-job-picker__list">
            {candidateStars.map((star) => {
              const checked = selectedJobIdSet.has(star.id)
              return (
                <label key={star.id} className={`graph-job-option ${checked ? 'is-selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleJobSelection(star.id)}
                  />
                  <span className="graph-job-option__check">{checked && <CheckOutlined />}</span>
                  <span className="graph-job-option__name">{star.label}</span>
                  <span className="graph-job-option__count">
                    {(star.jobCount ?? star.sources).toLocaleString('zh-CN')}
                  </span>
                </label>
              )
            })}
            {candidateStars.length === 0 && (
              <div className="graph-job-picker__empty">没有匹配岗位</div>
            )}
          </div>
        </div>
      )}
    </div>
  )

  return (
    <div className="graph-shell graph-shell--orbit relative min-h-screen pt-16 px-4 pb-4">
      {loading && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/90">
          <div className="text-center">
            <div className="loading-reticle mb-4" />
            <div className="text-[var(--text)] font-jetbrains">加载岗位星图...</div>
          </div>
        </div>
      )}

      {error && (
        <div className="graph-error">
          <div className="graph-error__inner glass p-3 px-4 flex items-center gap-2">
            <ExclamationCircleOutlined className="text-[#e4b592]" />
            <span className="text-sm text-[var(--text)]">{error}</span>
          </div>
        </div>
      )}

      <div className="graph-workspace">
        <aside className="graph-control-panel archive-panel glass">
          <FrameCorners />
          <div className="graph-control-panel__kicker">Orbit map / JD field</div>
          <h1>岗位-技能星图</h1>
          <p>{currentViewLabel}</p>

          <div className="graph-search-control archive-control">
            <SearchOutlined />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜索岗位、公司、技能"
            />
            {searchQuery && (
              <button type="button" onClick={() => setSearchQuery('')} aria-label="清空搜索">
                <CloseOutlined />
              </button>
            )}
          </div>

          {renderJobPicker()}

          <div className="graph-control-section">
            <div className="graph-control-section__title">技能轨道</div>
            <div className="graph-filter-stack">
              {(['core', 'foundation', 'frontier'] as const).map((type) => (
                <label key={type} className="graph-filter">
                  <input
                    type="checkbox"
                    checked={filterTypes.includes(type)}
                    onChange={() => toggleFilterType(type)}
                    style={{ accentColor: typeColor[type] }}
                  />
                  <span className="graph-filter__dot" style={{ background: typeColor[type] }} />
                  <span>{typeLabel[type]}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="graph-control-section">
            <div className="graph-control-section__title">文字层</div>
            <div className="graph-filter-stack graph-filter-stack--compact">
              <label className="graph-filter">
                <input
                  type="checkbox"
                  checked={showJobLabels}
                  onChange={(event) => setShowJobLabels(event.target.checked)}
                  style={{ accentColor: '#e4b592' }}
                />
                岗位标签
              </label>
              <label className="graph-filter">
                <input
                  type="checkbox"
                  checked={showSkillLabels}
                  onChange={(event) => setShowSkillLabels(event.target.checked)}
                  style={{ accentColor: '#ee1212' }}
                />
                技能标签
              </label>
            </div>
          </div>

          <div className="graph-data-strip">
            <div>
              <span>显示岗位</span>
              <strong>{visibleStars.length}</strong>
            </div>
            <div>
              <span>技能节点</span>
              <strong>{visiblePlanets.length}</strong>
            </div>
            <div>
              <span>JD 总量</span>
              <strong>{totalJobs.toLocaleString('zh-CN')}</strong>
            </div>
          </div>

          <div className="graph-source-mix">
            <span>{totalCategories} 个岗位类别</span>
            {sourceSummary.map(([source, count]) => (
              <strong key={source}>
                {source} {count.toLocaleString('zh-CN')}
              </strong>
            ))}
          </div>

          {selectedJobs.length > 0 && (
            <div className="graph-selected-jobs">
              {selectedJobs.slice(0, 6).map((star) => (
                <button
                  key={star.id}
                  type="button"
                  onClick={() => toggleJobSelection(star.id)}
                  style={{ borderColor: `${star.color}88` }}
                >
                  <span style={{ background: star.color }} />
                  {star.label}
                  <CloseOutlined />
                </button>
              ))}
              {selectedJobs.length > 6 && <em>+{selectedJobs.length - 6}</em>}
            </div>
          )}
        </aside>

        <section className="graph-canvas-frame graph-canvas-frame--archive relative overflow-hidden">
          <FrameCorners />
          <GraphScene3D
            data={{
              stars: visibleStars,
              planets: visiblePlanets,
              metadata: graphData.metadata,
            }}
            selectedStar={selectedStar}
            selectedPlanet={selectedPlanet}
            onStarClick={handleStarClick}
            onPlanetClick={handlePlanetClick}
            showJobLabels={effectiveShowJobLabels}
            showSkillLabels={effectiveShowSkillLabels}
            filterTypes={filterTypes}
          />

          <div className="graph-canvas-readout archive-panel glass">
            <span>{visibleStars.length} JOB NODES</span>
            <strong>{visiblePlanets.length} SKILL ORBITS</strong>
          </div>

          {visibleStars.length === 0 && (
            <div className="absolute inset-0 z-20 flex items-center justify-center pointer-events-none">
              <div className="archive-panel glass px-4 py-3 text-center max-w-[280px]">
                <div className="text-xs text-[var(--text)] font-medium mb-1">没有找到匹配的岗位</div>
                <div className="text-[10px] text-[var(--text-dim)]">清空搜索或换一个关键词</div>
              </div>
            </div>
          )}
        </section>
      </div>

      {selectedStar && (
        <>
          <div className="drawer-mask" onClick={closeDetail} />
          <div className="drawer drawer--archive graph-detail-drawer">
            <FrameCorners />
            <div className="graph-detail-header">
              <div className="graph-detail-header__meta">
                <span style={{ background: selectedStar.color }} />
                {selectedStar.domain}
              </div>
              <button type="button" onClick={closeDetail} aria-label="关闭详情">
                <CloseOutlined />
              </button>
            </div>

            <div className="drawer-node-kicker">Star node</div>
            <h2 style={{ color: selectedStar.color }}>{selectedStar.label}</h2>
            <div className="graph-detail-subtitle">
              基于 {(selectedStar.jobCount ?? selectedStar.sources).toLocaleString('zh-CN')} 条 JD 数据
            </div>

            <div className="graph-detail-metrics">
              <div>
                <span>JD 样本</span>
                <strong>{(selectedStar.jobCount ?? selectedStar.sources).toLocaleString('zh-CN')}</strong>
              </div>
              <div>
                <span>来源站点</span>
                <strong>{Object.keys(selectedStar.sourceCounts ?? {}).length || 1}</strong>
              </div>
              <div>
                <span>必备技能</span>
                <strong>{selectedStar.requiredSkills.length}</strong>
              </div>
              <div>
                <span>加分技能</span>
                <strong>{selectedStar.bonusSkills.length}</strong>
              </div>
            </div>

            {selectedStar.sourceCounts && (
              <div className="graph-detail-source">
                {Object.entries(selectedStar.sourceCounts).map(([source, count]) => (
                  <span key={source} className="badge-conf">
                    {source} {count.toLocaleString('zh-CN')}
                  </span>
                ))}
              </div>
            )}

            <div className="graph-detail-section">
              <div className="graph-detail-section__title">必备技能轨道</div>
              <div className="graph-detail-tags">
                {selectedStar.requiredSkills.map((skill) => (
                  <span key={skill} className="tag tag-orange">
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            <div className="graph-detail-section">
              <div className="graph-detail-section__title">加分技能轨道</div>
              <div className="graph-detail-tags">
                {selectedStar.bonusSkills.map((skill) => (
                  <span key={skill} className="tag tag-purple">
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            {selectedStar.sampleJobs && selectedStar.sampleJobs.length > 0 && (
              <div className="graph-detail-section">
                <div className="graph-detail-section__title">样例岗位</div>
                <div className="graph-sample-list">
                  {selectedStar.sampleJobs.slice(0, 4).map((job) => (
                    <a
                      key={`${job.url || job.jobName}-${job.companyName}`}
                      className="archive-row glass"
                      href={job.url || undefined}
                      target={job.url ? '_blank' : undefined}
                      rel={job.url ? 'noreferrer' : undefined}
                    >
                      <div className="graph-sample-list__dot" style={{ background: selectedStar.color }} />
                      <div>
                        <strong>{job.jobName}</strong>
                        <span>{job.companyName} · {job.city} · {job.salary || '薪资未标注'}</span>
                      </div>
                      <em>{job.source}</em>
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {selectedPlanet && planetStar && (
        <>
          <div className="drawer-mask" onClick={closeDetail} />
          <div className="drawer drawer--archive graph-detail-drawer">
            <FrameCorners />
            <div className="graph-detail-header">
              <span className={`tag tag-${selectedPlanet.type === 'core' ? 'orange' : selectedPlanet.type === 'foundation' ? 'green' : 'purple'}`}>
                {typeLabel[selectedPlanet.type]}
              </span>
              <button type="button" onClick={closeDetail} aria-label="关闭详情">
                <CloseOutlined />
              </button>
            </div>

            <div className="drawer-node-kicker">Skill node</div>
            <h2 style={{ color: typeColor[selectedPlanet.type] }}>{selectedPlanet.label}</h2>
            <div className="graph-detail-subtitle">
              {selectedPlanet.isRequired ? '必备技能（内环）' : '加分技能（外环）'} · 隶属 {planetStar.label}
            </div>

            <div className="graph-detail-section">
              <div className="flex justify-between mb-2">
                <span className="text-xs text-[var(--text-dim)]">AI 置信度</span>
                <span className="badge-conf">{Math.round(selectedPlanet.confidence)}%</span>
              </div>
              <div className="prog-track">
                <div
                  className="prog-fill"
                  style={{
                    width: `${Math.round(selectedPlanet.confidence)}%`,
                    background: `linear-gradient(90deg, ${typeColor[selectedPlanet.type]}, ${typeColor[selectedPlanet.type]}80)`,
                  }}
                />
              </div>
            </div>

            <div className="graph-detail-section">
              <div className="graph-detail-section__title">需要该技能的岗位</div>
              <div className="graph-sample-list">
                {graphData.stars
                  .filter((star) => [...star.requiredSkills, ...star.bonusSkills].includes(selectedPlanet.label))
                  .map((star) => (
                    <button key={star.id} type="button" className="archive-row glass" onClick={() => handleStarClick(star)}>
                      <div className="graph-sample-list__dot" style={{ background: star.color }} />
                      <div>
                        <strong>{star.label}</strong>
                        <span>{star.domain}</span>
                      </div>
                      <em>{star.requiredSkills.includes(selectedPlanet.label) ? '必备' : '加分'}</em>
                    </button>
                  ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
