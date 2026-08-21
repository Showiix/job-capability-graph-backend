import { useEffect, useMemo, useRef, useState } from 'react'
import { GraphScene3D } from '../components/GraphScene3D'
import MOCK_GRAPH_DATA from '../data/mockGraphData'
import { fetchGraphData } from '../services/graphApi'
import type { Star, Planet, GraphData } from '../types/graph'
import {
  ExclamationCircleOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  SearchOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'

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

const ALL_JOBS = '__all__'
const FEATURED_LIMIT = 8

type ViewSnapshot = {
  displayMode: 'featured' | 'all'
  focusedJobId: string
  searchQuery: string
}

export default function SpaceGraphPage() {
  const [graphData, setGraphData] = useState<GraphData>(MOCK_GRAPH_DATA)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedStar, setSelectedStar] = useState<Star | null>(null)
  const [selectedPlanet, setSelectedPlanet] = useState<Planet | null>(null)
  const [filterTypes, setFilterTypes] = useState<string[]>(['core', 'foundation', 'frontier'])
  const [showLabels, setShowLabels] = useState(true)
  const [focusedJobId, setFocusedJobId] = useState<string>(ALL_JOBS)
  const [searchQuery, setSearchQuery] = useState('')
  const [displayMode, setDisplayMode] = useState<'featured' | 'all'>('featured')
  const viewSnapshotRef = useRef<ViewSnapshot>({
    displayMode: 'featured',
    focusedJobId: ALL_JOBS,
    searchQuery: '',
  })

  useEffect(() => {
    async function loadGraphData() {
      try {
        setLoading(true)
        setError(null)
        const data = await fetchGraphData()
        setGraphData(data)
      } catch (err) {
        console.error('Failed to load graph data:', err)
        setError('加载图谱数据失败，使用本地样例')
        setGraphData(MOCK_GRAPH_DATA)
      } finally {
        setLoading(false)
      }
    }

    loadGraphData()
  }, [])

  const featuredStarIds = graphData.metadata?.featured_star_ids ?? []
  const featuredStars = useMemo(() => {
    const preferred = featuredStarIds
      .map((id) => graphData.stars.find((star) => star.id === id))
      .filter(Boolean) as Star[]

    if (preferred.length > 0) {
      if (preferred.length >= FEATURED_LIMIT) {
        return preferred.slice(0, FEATURED_LIMIT)
      }

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
    if (!query) {
      return graphData.stars
    }

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

  const candidateStars = searchQuery.trim() ? searchResults : graphData.stars

  const visibleStars = useMemo(() => {
    if (searchQuery.trim()) {
      return searchResults
    }

    if (displayMode === 'all' || focusedJobId !== ALL_JOBS) {
      return graphData.stars
    }
    return featuredStars.length > 0 ? featuredStars : graphData.stars.slice(0, FEATURED_LIMIT)
  }, [displayMode, featuredStars, focusedJobId, graphData.stars, searchQuery, searchResults])

  const visibleStarIds = useMemo(() => new Set(visibleStars.map((star) => star.id)), [visibleStars])
  const visiblePlanets = useMemo(
    () =>
      graphData.planets.filter(
        (planet) => filterTypes.includes(planet.type) && visibleStarIds.has(planet.starId)
      ),
    [filterTypes, graphData.planets, visibleStarIds]
  )

  const captureViewSnapshot = () => {
    if (selectedStar || selectedPlanet) {
      return
    }

    viewSnapshotRef.current = {
      displayMode,
      focusedJobId,
      searchQuery,
    }
  }

  const restoreViewSnapshot = () => {
    const snapshot = viewSnapshotRef.current
    setDisplayMode(snapshot.displayMode)
    setFocusedJobId(snapshot.focusedJobId)
    setSearchQuery(snapshot.searchQuery)
    setSelectedStar(null)
    setSelectedPlanet(null)
  }

  const handleStarClick = (star: Star) => {
    captureViewSnapshot()
    setSelectedStar(star)
    setSelectedPlanet(null)
    setFocusedJobId(star.id)
  }

  const handlePlanetClick = (planet: Planet) => {
    captureViewSnapshot()
    setSelectedPlanet(planet)
    setSelectedStar(null)
    setFocusedJobId(planet.starId)
  }

  const resetSelection = () => {
    restoreViewSnapshot()
  }

  const toggleFilterType = (type: string) => {
    setFilterTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]))
  }

  const handleFocusJob = (jobId: string) => {
    if (jobId === ALL_JOBS) {
      setDisplayMode('all')
      setFocusedJobId(ALL_JOBS)
      setSelectedStar(null)
      setSelectedPlanet(null)
      return
    }

    const job = graphData.stars.find((star) => star.id === jobId)
    if (job) {
      captureViewSnapshot()
      setFocusedJobId(jobId)
      setSelectedStar(job)
      setSelectedPlanet(null)
      const isFeaturedJob = featuredStars.some((star) => star.id === jobId)
      if (!isFeaturedJob) {
        setDisplayMode('all')
      }
    }
  }

  const handleDisplayMode = (mode: 'featured' | 'all') => {
    setDisplayMode(mode)
    setFocusedJobId(ALL_JOBS)
    setSelectedStar(null)
    setSelectedPlanet(null)
  }

  const planetStar = selectedPlanet ? graphData.stars.find((star) => star.id === selectedPlanet.starId) : null
  const isFocused = focusedJobId !== ALL_JOBS
  const focusedStar = isFocused ? graphData.stars.find((star) => star.id === focusedJobId) : null
  const currentViewLabel =
    displayMode === 'featured'
      ? '热门新兴视角'
      : focusedJobId === ALL_JOBS
        ? '全量岗位视角'
        : '岗位聚焦视角'
  const totalJobs = graphData.metadata?.total_jobs ?? graphData.stars.reduce((sum, star) => sum + (star.jobCount ?? star.sources ?? 0), 0)
  const totalCategories = graphData.metadata?.total_categories ?? graphData.stars.length
  const sourceCounts = graphData.metadata?.source_counts ?? {}
  const sourceSummary = Object.entries(sourceCounts)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)

  const renderJobSwitcher = () => (
    <div className="archive-panel glass rounded-xl p-3 px-4 mb-4">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <button className="btn btn-sm btn-ghost" onClick={restoreViewSnapshot}>
          <ReloadOutlined /> 返回原视角
        </button>
        <button
          className={`btn btn-sm ${displayMode === 'featured' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => handleDisplayMode('featured')}
        >
          热门新兴
        </button>
        <button
          className={`btn btn-sm ${displayMode === 'all' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => handleDisplayMode('all')}
        >
          所有岗位
        </button>
      </div>

      <div className="archive-control flex items-center gap-2 glass rounded-lg px-3 py-2 mb-2">
        <SearchOutlined className="text-[var(--text-dim)]" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索岗位、公司、技能"
          className="bg-transparent border-none outline-none text-sm text-[var(--text)] placeholder-[var(--text-dim)] flex-1 min-w-0"
        />
      </div>

      <div className="max-h-56 overflow-y-auto pr-1 space-y-1.5">
        {candidateStars.slice(0, 12).map((star) => {
          const checked = focusedJobId === star.id
          return (
            <label
              key={star.id}
              className="archive-row glass rounded-lg px-3 py-2 flex items-center gap-2 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => {
                  if (checked) {
                    restoreViewSnapshot()
                  } else {
                    handleFocusJob(star.id)
                  }
                }}
                style={{ accentColor: star.color }}
              />
              <span className="text-[12px] text-[var(--text)] flex-1 truncate">{star.label}</span>
              <span className="badge-conf">{star.sources}</span>
            </label>
          )
        })}
        {candidateStars.length > 12 && (
          <div className="text-[10px] text-[var(--text-dim)]">...及其他 {candidateStars.length - 12} 个岗位</div>
        )}
      </div>
    </div>
  )

  return (
    <div className="graph-shell relative h-screen pt-14 flex flex-col">
      {loading && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-space-bg bg-opacity-90">
          <div className="text-center">
            <div className="loading-reticle mb-4" />
            <div className="text-space-cyan font-jetbrains">加载图谱数据中...</div>
          </div>
        </div>
      )}

      {error && (
        <div className="graph-error absolute z-20">
          <div className="graph-error__inner glass p-3 px-4 flex items-center gap-2">
            <ExclamationCircleOutlined className="text-[#e4b592]" />
            <span className="text-sm text-[var(--text)]">{error}</span>
          </div>
        </div>
      )}

      <div className="graph-toolbar graph-toolbar--archive mx-4 mt-2 z-10 flex flex-wrap items-center gap-3">
        <FrameCorners />
        <div className="flex-1 min-w-[220px]">
          <div className="graph-toolbar__eyebrow">Orbit map / JD field</div>
          <h1 className="text-xl font-bold text-[var(--text)] mb-1">岗位-技能星图</h1>
          <p className="text-xs text-[var(--text-dim)]">
            默认只展示热门新兴岗位，搜索和下拉可切到全量岗位
          </p>
          <p className="text-[10px] text-[var(--text-dim)] mt-1">当前视角：{currentViewLabel}</p>
        </div>

        <div className="archive-control flex items-center gap-2 glass rounded-lg px-3 py-2 min-w-[220px]">
          <SearchOutlined className="text-[var(--text-dim)]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索岗位、公司、技能"
            className="bg-transparent border-none outline-none text-sm text-[var(--text)] placeholder-[var(--text-dim)] flex-1"
          />
        </div>

        <div className="flex items-center gap-2">
          <select
            value={focusedJobId}
            onChange={(e) => handleFocusJob(e.target.value)}
            className="archive-control glass rounded-lg px-3 py-2 text-sm text-[var(--text)] bg-transparent border border-[var(--border)] cursor-pointer hover:border-[var(--color-primary)] transition-colors min-w-[220px]"
          >
            <option value={ALL_JOBS}>全部岗位星系</option>
            {candidateStars.map((star) => (
              <option key={star.id} value={star.id}>
                {star.label}
              </option>
            ))}
          </select>

          {isFocused ? (
            <button className="btn btn-sm btn-ghost flex items-center gap-1" onClick={() => handleFocusJob(ALL_JOBS)}>
              <ZoomOutOutlined /> 所有岗位
            </button>
          ) : (
            <span className="text-xs text-[var(--text-dim)] flex items-center gap-1">
              <ZoomInOutlined /> 点击岗位进入详情
            </span>
          )}
        </div>
      </div>

      <div className="graph-toolbar mx-4 mt-2 z-10">
        <div className="graph-toolbar__group">
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

        <div className="graph-toolbar__divider" />

        <div className="graph-toolbar__group">
          <button
            className={`btn btn-sm ${displayMode === 'featured' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => handleDisplayMode('featured')}
          >
            热门新兴
          </button>
          <button
            className={`btn btn-sm ${displayMode === 'all' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => handleDisplayMode('all')}
          >
            全量岗位
          </button>
        </div>

        <div className="graph-toolbar__divider" />

        <label className="graph-filter">
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.target.checked)}
            style={{ accentColor: '#ee1212' }}
          />
          常驻标签
        </label>

        <div className="graph-toolbar__divider" />

        <span className="graph-toolbar__hint">
          {totalCategories} 个岗位类别 · {totalJobs.toLocaleString('zh-CN')} 条 JD · {graphData.planets.length} 个技能节点
        </span>

        <div className="graph-toolbar__actions">
          <button className="btn btn-sm btn-ghost" onClick={restoreViewSnapshot}>
            <ReloadOutlined /> 返回原视角
          </button>
          <button className="btn btn-sm btn-primary">
            <FileSearchOutlined /> 简历匹配
          </button>
        </div>
      </div>

      <div className="graph-toolbar mx-4 mt-2 z-10 flex flex-wrap items-center gap-3">
        <div className="archive-panel glass rounded-xl px-4 py-2 flex flex-wrap items-center gap-3">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-dim)]">Source mix</span>
          {sourceSummary.map(([source, count]) => (
            <span key={source} className="badge-conf">
              {source} {count.toLocaleString('zh-CN')}
            </span>
          ))}
          {featuredStars.length > 0 && (
            <span className="text-[10px] text-[var(--text-dim)]">
              默认视图: {featuredStars.map((star) => star.label).slice(0, 4).join(' / ')}
            </span>
          )}
        </div>
      </div>

      <div className="graph-legend-wrap absolute bottom-5 left-6 z-10">
        <div className="graph-legend archive-panel glass rounded-xl p-3 px-4 flex flex-col gap-2">
          <FrameCorners />
          <div className="graph-legend__title text-[10px] text-[var(--text-dim)] font-jetbrains mb-1">
            {isFocused ? `聚焦: ${focusedStar?.label}` : displayMode === 'featured' ? '默认热门新兴岗位' : '图例'}
          </div>
          {isFocused && focusedStar ? (
            <>
              <div className="flex items-center gap-2 mb-2">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ background: focusedStar.color, boxShadow: `0 0 8px ${focusedStar.color}` }}
                />
                <div>
                  <span className="text-[12px] text-[var(--text)] font-semibold block">{focusedStar.label}</span>
                  <span className="text-[10px] text-[var(--text-dim)]">{focusedStar.domain}</span>
                </div>
              </div>
              <div className="text-[10px] text-[var(--text-dim)]">
                JD 数量: {focusedStar.jobCount ?? focusedStar.sources} · 源站: {focusedStar.sources}
              </div>
            </>
          ) : (
            <>
              {visibleStars.slice(0, 8).map((star) => (
                <div
                  key={star.id}
                  className="flex items-center gap-2 cursor-pointer hover:opacity-80"
                  onClick={() => handleFocusJob(star.id)}
                >
                  <div
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ background: star.color, boxShadow: `0 0 6px ${star.color}` }}
                  />
                  <span className="text-[11px] text-[#dad0c8]">{star.label}</span>
                </div>
              ))}
              {visibleStars.length > 8 && (
                <div className="text-[10px] text-[#a49b92]">...及其他 {visibleStars.length - 8} 个岗位</div>
              )}
            </>
          )}
          <div className="border-t border-[var(--border)] mt-1 pt-2 flex flex-col gap-1.5">
            {(['core', 'foundation', 'frontier'] as const).map((type) => (
              <div key={type} className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full" style={{ background: typeColor[type] }} />
                <span className="text-[10px] text-[#a49b92]">{typeLabel[type]}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="graph-canvas-frame graph-canvas-frame--archive flex-1 relative mx-4 mb-4 rounded-2xl overflow-hidden">
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
          showLabels={showLabels}
          filterTypes={filterTypes}
          focusedJobId={isFocused ? focusedJobId : undefined}
        />
        {searchQuery.trim() && visibleStars.length === 0 && (
          <div className="absolute inset-0 z-20 flex items-center justify-center pointer-events-none">
            <div className="archive-panel glass rounded-xl px-4 py-3 text-center max-w-[280px]">
              <div className="text-xs text-[var(--text)] font-medium mb-1">没有找到匹配的岗位</div>
              <div className="text-[10px] text-[var(--text-dim)]">换个关键词，或者清空搜索看看全量岗位星系</div>
            </div>
          </div>
        )}
      </div>

      {selectedStar && (
        <>
          <div className="drawer-mask" onClick={resetSelection} />
          <div className="drawer drawer--archive p-7">
            <FrameCorners />
            <div className="flex justify-between items-start mb-5">
              <div className="flex items-center gap-2.5">
                <div
                  className="w-3.5 h-3.5 rounded-full"
                  style={{ background: selectedStar.color, boxShadow: `0 0 12px ${selectedStar.color}` }}
                />
                <span className="text-[11px] text-[var(--text-dim)] font-jetbrains">
                  {selectedStar.domain}
                </span>
              </div>
              <button className="bg-transparent border-none text-[var(--text-dim)] cursor-pointer text-xl" onClick={resetSelection}>
                ×
              </button>
            </div>

            <div className="drawer-node-kicker">Star node</div>
            <h2
              className="font-outfit font-extrabold text-3xl md:text-4xl leading-[0.95] mb-1.5"
              style={{ color: selectedStar.color, textShadow: `0 0 20px ${selectedStar.color}60` }}
            >
              {selectedStar.label}
            </h2>
            <div className="text-xs text-[var(--text-dim)] mb-5">
              恒星节点 · 基于 {selectedStar.jobCount ?? selectedStar.sources} 条 JD 数据
            </div>

            {renderJobSwitcher()}

            <div className="archive-panel glass rounded-xl p-3 px-4 mb-4">
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div className="border border-[var(--border)] px-3 py-2">
                  <div className="text-[10px] text-[var(--text-dim)]">JD 样本</div>
                  <div className="text-base text-[var(--text)] font-semibold">
                    {(selectedStar.jobCount ?? selectedStar.sources).toLocaleString('zh-CN')}
                  </div>
                </div>
                <div className="border border-[var(--border)] px-3 py-2">
                  <div className="text-[10px] text-[var(--text-dim)]">来源站点</div>
                  <div className="text-base text-[var(--text)] font-semibold">
                    {Object.keys(selectedStar.sourceCounts ?? {}).length || 1}
                  </div>
                </div>
                <div className="border border-[var(--border)] px-3 py-2">
                  <div className="text-[10px] text-[var(--text-dim)]">必备技能</div>
                  <div className="text-base text-[var(--text)] font-semibold">{selectedStar.requiredSkills.length}</div>
                </div>
                <div className="border border-[var(--border)] px-3 py-2">
                  <div className="text-[10px] text-[var(--text-dim)]">加分技能</div>
                  <div className="text-base text-[var(--text)] font-semibold">{selectedStar.bonusSkills.length}</div>
                </div>
              </div>
              <div className="flex justify-between mb-2">
                <span className="text-xs text-[var(--text-dim)]">数据覆盖度</span>
                <span className="badge-conf">92%</span>
              </div>
              <div className="prog-track">
                <div
                  className="prog-fill"
                  style={{ width: '92%', background: `linear-gradient(90deg, ${selectedStar.color}, ${selectedStar.color}aa)` }}
                />
              </div>
              {selectedStar.sourceCounts && (
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {Object.entries(selectedStar.sourceCounts).map(([source, count]) => (
                    <span key={source} className="badge-conf">
                      {source} {count.toLocaleString('zh-CN')}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="mb-4">
              <div className="text-[11px] text-[var(--text-dim)] mb-2">必备技能轨道</div>
              <div className="flex flex-wrap gap-1.5">
                {selectedStar.requiredSkills.map((skill) => (
                  <span key={skill} className="tag tag-orange">
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <div className="text-[11px] text-[var(--text-dim)] mb-2">加分技能轨道（外环）</div>
              <div className="flex flex-wrap gap-1.5">
                {selectedStar.bonusSkills.map((skill) => (
                  <span key={skill} className="tag tag-purple">
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            {selectedStar.sampleJobs && selectedStar.sampleJobs.length > 0 && (
              <div className="mt-5">
                <div className="text-[11px] text-[var(--text-dim)] mb-2">样例岗位</div>
                <div className="space-y-2">
                  {selectedStar.sampleJobs.slice(0, 3).map((job) => (
                    <a
                      key={`${job.url || job.jobName}-${job.companyName}`}
                      className="archive-row glass rounded-lg p-2.5 px-3.5 flex items-center gap-2.5"
                      href={job.url || undefined}
                      target={job.url ? '_blank' : undefined}
                      rel={job.url ? 'noreferrer' : undefined}
                    >
                      <div className="w-2 h-2 rounded-full" style={{ background: selectedStar.color }} />
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] text-[var(--text)] font-medium truncate">{job.jobName}</div>
                        <div className="text-[10px] text-[var(--text-dim)] truncate">
                          {job.companyName} · {job.city} · {job.salary || '薪资未标注'}
                        </div>
                      </div>
                      <span className="badge-conf">{job.source}</span>
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
          <div className="drawer-mask" onClick={resetSelection} />
          <div className="drawer drawer--archive p-7">
            <FrameCorners />
            <div className="flex justify-between mb-5">
              <span
                className={`tag tag-${selectedPlanet.type === 'core' ? 'orange' : selectedPlanet.type === 'foundation' ? 'green' : 'purple'}`}
              >
                {typeLabel[selectedPlanet.type]}
              </span>
              <div className="flex items-center gap-2">
                <button className="btn btn-sm btn-ghost" onClick={restoreViewSnapshot}>
                  <ReloadOutlined /> 返回原视角
                </button>
                <button className="bg-transparent border-none text-[var(--text-dim)] cursor-pointer text-xl" onClick={resetSelection}>
                  ×
                </button>
              </div>
            </div>

            <div className="drawer-node-kicker">Skill node</div>
            <h2 className="font-outfit font-extrabold text-2xl md:text-3xl leading-[1] mb-1.5" style={{ color: typeColor[selectedPlanet.type] }}>
              {selectedPlanet.label}
            </h2>
            <div className="text-xs text-[var(--text-dim)] mb-5">
              {selectedPlanet.isRequired ? '必备技能（内环）' : '加分技能（外环）'} · 隶属 {planetStar.label}
            </div>

            {renderJobSwitcher()}

            <div className="archive-panel glass rounded-xl p-3 px-4 mb-4">
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

            <div className="text-[11px] text-[var(--text-dim)] mb-2.5">需要该技能的岗位</div>
            {graphData.stars
              .filter((star) => [...star.requiredSkills, ...star.bonusSkills].includes(selectedPlanet.label))
              .map((star) => (
                <div key={star.id} className="archive-row glass rounded-lg p-2.5 px-3.5 mb-2 flex items-center gap-2.5">
                  <div className="w-2 h-2 rounded-full" style={{ background: star.color, boxShadow: `0 0 6px ${star.color}` }} />
                  <span className="text-[13px] text-[var(--text)] font-medium flex-1">{star.label}</span>
                  <span className="badge-conf">{star.requiredSkills.includes(selectedPlanet.label) ? '必备' : '加分'}</span>
                </div>
              ))}
          </div>
        </>
      )}
    </div>
  )
}
