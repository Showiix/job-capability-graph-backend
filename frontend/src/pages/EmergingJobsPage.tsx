import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Select } from 'antd'
import {
  BarChartOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  FileSearchOutlined,
  FilterOutlined,
  ReloadOutlined,
  RiseOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  TagsOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { FrameCorners } from '../components/FrameCorners'
import { getEmergingJobs } from '../services/emergingJobsApi'
import type {
  EmergingJobDefinition,
  EmergingJobsResponse,
  EmergingSkillDefinition,
} from '../types/api'

type SortBy = 'jdCount' | 'companyCount' | 'title'
type StatusFilter = 'all' | 'pending' | 'approved' | 'rejected'

const STATUS_LABELS: Record<StatusFilter, string> = {
  all: '全部状态',
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
}

function cleanIndustry(value: string) {
  return value
    .replace(/[（(].*?[）)]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function jobIndustryLabels(job: EmergingJobDefinition) {
  return Array.from(
    new Set(job.industryScenes.map(cleanIndustry).filter(Boolean)),
  )
}

function formatNumber(value: number) {
  return value.toLocaleString('zh-CN')
}

function percentageLabel(value: number | null) {
  return value === null ? '技术词' : `${value}%`
}

function getSkillChartData(job: EmergingJobDefinition) {
  return [...job.requiredSkills, ...job.bonusSkills]
    .filter((skill) => skill.percentage !== null)
    .sort((a, b) => (b.percentage ?? 0) - (a.percentage ?? 0))
    .slice(0, 10)
    .map((skill) => ({
      name: skill.name,
      percentage: skill.percentage ?? 0,
    }))
}

function getStatusColor(status: string) {
  if (status === 'approved') return '#dad0c8'
  if (status === 'rejected') return '#ee1212'
  return '#e4b592'
}

function skillChip(skill: EmergingSkillDefinition, role: 'required' | 'bonus') {
  return (
    <span
      key={`${role}-${skill.name}`}
      className={`tag ${role === 'required' ? 'tag-orange' : 'tag-purple'}`}
      title={role === 'required' ? '必备技术词' : '加分技术词'}
    >
      {skill.name}
      <small>{percentageLabel(skill.percentage)}</small>
    </span>
  )
}

export default function EmergingJobsPage() {
  const [snapshot, setSnapshot] = useState<EmergingJobsResponse | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [industryFilter, setIndustryFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [sortBy, setSortBy] = useState<SortBy>('jdCount')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadJobs = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getEmergingJobs({ sort_by: sortBy })
      setSnapshot(data)
    } catch (apiError) {
      try {
        const response = await fetch('/emerging_jobs.json')
        if (!response.ok) throw new Error('静态数据读取失败')
        setSnapshot((await response.json()) as EmergingJobsResponse)
        setError('后端接口暂不可用，当前使用 Excel 生成的本地快照')
      } catch {
        const value = apiError as { apiMessage?: string; message?: string }
        setError(value.apiMessage || value.message || '新兴岗位数据读取失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadJobs()
  }, [sortBy])

  const jobs = snapshot?.jobs ?? []
  const summary = snapshot?.summary
  const industryOptions = useMemo(() => {
    const values = jobs.flatMap(jobIndustryLabels)
    return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, 'zh-CN'))
  }, [jobs])

  const filteredJobs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return jobs
      .filter((job) => {
        if (statusFilter !== 'all' && job.reviewStatusCode !== statusFilter) return false
        if (industryFilter !== 'all' && !jobIndustryLabels(job).includes(industryFilter)) return false
        if (!query) return true
        const searchable = [
          job.title,
          job.normalizedName,
          ...job.aliases,
          ...jobIndustryLabels(job),
          ...job.requiredSkills.map((skill) => skill.name),
          ...job.bonusSkills.map((skill) => skill.name),
        ]
          .join(' ')
          .toLowerCase()
        return searchable.includes(query)
      })
      .sort((a, b) => {
        if (sortBy === 'companyCount') return b.companyCount - a.companyCount
        if (sortBy === 'title') return a.title.localeCompare(b.title, 'zh-CN')
        return b.jdCount - a.jdCount || b.companyCount - a.companyCount
      })
  }, [industryFilter, jobs, searchQuery, sortBy, statusFilter])

  useEffect(() => {
    if (filteredJobs.length === 0) {
      setSelectedJobId(null)
      return
    }
    if (!selectedJobId || !filteredJobs.some((job) => job.id === selectedJobId)) {
      setSelectedJobId(filteredJobs[0].id)
    }
  }, [filteredJobs, selectedJobId])

  const selectedJob = filteredJobs.find((job) => job.id === selectedJobId) ?? filteredJobs[0] ?? null
  const selectedSkillChart = selectedJob ? getSkillChartData(selectedJob) : []
  const industryChart = (summary?.industryStats ?? [])
    .filter((item) => item.jdCount > 0)
    .slice(0, 10)
    .map((item) => ({
      name: cleanIndustry(item.name),
      jdCount: item.jdCount,
    }))

  const stats = [
    { label: '岗位定义', value: summary?.definitionCount ?? 0, suffix: '条', color: '#e4b592' },
    { label: '覆盖 JD', value: summary?.totalJdCount ?? 0, suffix: '条', color: '#fff3ea' },
    { label: '技术词', value: summary?.skillCount ?? 0, suffix: '项', color: '#dad0c8' },
    { label: '待审核', value: summary?.statusCounts.pending ?? 0, suffix: '条', color: '#ee1212' },
  ]

  return (
    <div className="page-shell page-shell--emerging min-h-screen pt-14">
      <div className="page-shell__inner max-w-7xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive">
          <FrameCorners />
          <div className="page-head__icon">
            <RiseOutlined />
          </div>
          <div className="page-head__copy">
            <div className="page-head__eyebrow">Workbook snapshot / emerging roles</div>
            <h1 className="page-head__title">新兴岗位发现</h1>
            <p className="page-head__desc">
              基于岗位定义、JD 覆盖、行业场景和技术词，查看待审核的新岗位候选。
            </p>
          </div>
        </div>

        {error && (
          <div className="emerging-data-notice archive-panel glass mb-6">
            <span><DatabaseOutlined /> {error}</span>
            <button type="button" onClick={() => void loadJobs()} aria-label="重新加载新兴岗位数据">
              <ReloadOutlined />
            </button>
          </div>
        )}

        <div className="emerging-stats mb-8">
          {stats.map((stat, index) => (
            <div
              key={stat.label}
              className={`metric-card archive-metric emerging-stat ${index === 0 ? 'emerging-stat--primary' : ''} animate-fade-up`}
              style={{ '--accent': stat.color } as CSSProperties}
            >
              <div className="metric-card__label">{stat.label}</div>
              <div className="metric-card__value" style={{ color: stat.color }}>
                {loading ? '—' : formatNumber(stat.value)}
                <span className="text-base ml-1">{stat.suffix}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="emerging-workspace-grid">
          <div className="emerging-job-rail">
            <div className="archive-panel glass rounded-2xl p-4">
              <FrameCorners />
              <div className="flex justify-between items-center mb-4 gap-3">
                <div>
                  <h2 className="font-outfit font-bold text-base text-[var(--text)]">岗位定义库</h2>
                  <div className="font-jetbrains text-[9px] text-[var(--text-dim)] mt-1">
                    {filteredJobs.length} / {jobs.length} RECORDS
                  </div>
                </div>
                <Select
                  value={sortBy}
                  onChange={(value: SortBy) => setSortBy(value)}
                  aria-label="排序岗位定义"
                  className="min-w-36"
                  options={[
                    { value: 'jdCount', label: '按 JD 覆盖' },
                    { value: 'companyCount', label: '按公司数' },
                    { value: 'title', label: '按岗位名' },
                  ]}
                />
              </div>

              <div className="emerging-search-control archive-control mb-3">
                <SearchOutlined />
                <input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索岗位、别称、技术词"
                  aria-label="搜索新兴岗位"
                />
              </div>

              <div className="emerging-filter-grid mb-4">
                <label className="emerging-filter-field">
                  <span><FilterOutlined /> 行业</span>
                  <Select
                    value={industryFilter}
                    onChange={setIndustryFilter}
                    aria-label="行业筛选"
                    className="w-full"
                    options={[
                      { value: 'all', label: '全部行业' },
                      ...industryOptions.map((industry) => ({ value: industry, label: industry })),
                    ]}
                  />
                </label>
                <label className="emerging-filter-field">
                  <span><CheckCircleOutlined /> 状态</span>
                  <Select
                    value={statusFilter}
                    onChange={(value: StatusFilter) => setStatusFilter(value)}
                    aria-label="状态筛选"
                    className="w-full"
                    options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))}
                  />
                </label>
              </div>

              <div className="emerging-job-list space-y-2 max-h-[600px] overflow-y-auto pr-2">
                {loading && <div className="emerging-empty-state">正在读取 Excel 生成的数据快照…</div>}
                {!loading && filteredJobs.map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    className={`archive-row market-archive-row glass rounded-xl p-3 text-left cursor-pointer transition-all ${
                      selectedJob?.id === job.id ? 'is-selected' : ''
                    }`}
                    onClick={() => setSelectedJobId(job.id)}
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="min-w-0">
                        <div className="font-outfit font-bold text-sm text-[var(--text)] mb-1 truncate">
                          {job.title}
                        </div>
                        <div className="text-xs text-[var(--text-dim)] truncate">
                          {cleanIndustry(job.primaryIndustry)}
                        </div>
                      </div>
                      <span
                        className="emerging-status-badge"
                        style={{ color: getStatusColor(job.reviewStatusCode) }}
                      >
                        {job.reviewStatus}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3 font-jetbrains text-[10px] text-[var(--text-dim)]">
                      <span><DatabaseOutlined /> {formatNumber(job.jdCount)} JD</span>
                      <span><TeamOutlined /> {formatNumber(job.companyCount)} 公司</span>
                    </div>
                  </button>
                ))}
                {!loading && filteredJobs.length === 0 && (
                  <div className="emerging-empty-state">
                    没有符合当前搜索和筛选条件的岗位定义。
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="emerging-insight-stack space-y-6">
            {selectedJob ? (
              <>
                <div className="archive-panel glass rounded-2xl p-6">
                  <FrameCorners />
                  <div className="emerging-detail-heading">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <RiseOutlined className="text-xl text-[#ee1212]" />
                        <h2 className="font-outfit font-extrabold text-2xl text-[var(--text)]">
                          {selectedJob.title}
                        </h2>
                        <span
                          className="emerging-status-badge emerging-status-badge--large"
                          style={{ color: getStatusColor(selectedJob.reviewStatusCode) }}
                        >
                          {selectedJob.reviewStatus}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-sm text-[var(--text-dim)] flex-wrap">
                        <span><TagsOutlined /> {cleanIndustry(selectedJob.primaryIndustry)}</span>
                        <span><DatabaseOutlined /> {formatNumber(selectedJob.jdCount)} 条 JD</span>
                        <span><TeamOutlined /> {formatNumber(selectedJob.companyCount)} 家公司</span>
                      </div>
                    </div>
                    <div className="emerging-definition-id">
                      <span>DEFINITION ID</span>
                      <strong>{selectedJob.id}</strong>
                    </div>
                  </div>

                  <div className="emerging-detail-grid mt-6">
                    <div>
                      <div className="emerging-section-label">核心职责</div>
                      <div className="emerging-responsibility-list">
                        {selectedJob.responsibilities.map((item) => (
                          <div key={item}><span>+</span>{item}</div>
                        ))}
                      </div>
                    </div>
                    <div className="emerging-facts">
                      <div><span>LLM 精炼</span><strong>{selectedJob.llmRefined ? '是' : '否'}</strong></div>
                      <div><span>必备技术词</span><strong>{selectedJob.requiredSkills.length}</strong></div>
                      <div><span>加分技术词</span><strong>{selectedJob.bonusSkills.length}</strong></div>
                      <div><span>去重 JD</span><strong>{formatNumber(selectedJob.jdCount)}</strong></div>
                    </div>
                  </div>

                  <div className="emerging-detail-section">
                    <div className="emerging-section-label"><SafetyCertificateOutlined /> 必备技术词</div>
                    <div className="flex flex-wrap gap-2">
                      {selectedJob.requiredSkills.map((skill) => skillChip(skill, 'required'))}
                    </div>
                  </div>

                  <div className="emerging-detail-section">
                    <div className="emerging-section-label"><RiseOutlined /> 加分技术词</div>
                    <div className="flex flex-wrap gap-2">
                      {selectedJob.bonusSkills.map((skill) => skillChip(skill, 'bonus'))}
                    </div>
                  </div>

                  <div className="emerging-detail-section emerging-detail-columns">
                    <div>
                      <div className="emerging-section-label"><EnvironmentOutlined /> 行业场景</div>
                      <div className="emerging-inline-list">
                        {jobIndustryLabels(selectedJob).map((scene) => <span key={scene}>{scene}</span>)}
                      </div>
                    </div>
                    <div>
                      <div className="emerging-section-label"><TeamOutlined /> 代表公司</div>
                      <div className="emerging-inline-list">
                        {selectedJob.representativeCompanies.slice(0, 6).map((company) => <span key={company}>{company}</span>)}
                      </div>
                    </div>
                  </div>

                  <div className="emerging-source-note">
                    <FileSearchOutlined />
                    别称：{selectedJob.aliases.slice(0, 5).join(' · ') || '暂无别称'}
                  </div>
                </div>

                <div className="emerging-chart-grid">
                  <div className="archive-panel chart-archive-panel glass rounded-2xl p-6">
                    <FrameCorners />
                    <h3 className="font-outfit font-bold text-base text-[var(--text)] mb-1">
                      <BarChartOutlined /> 当前岗位技能频率
                    </h3>
                    <p className="text-xs text-[var(--text-dim)] mb-4">来自岗位定义表中的技能百分比</p>
                    {selectedSkillChart.length > 0 ? (
                      <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={selectedSkillChart} layout="vertical" margin={{ left: 12, right: 18 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,243,234,0.1)" />
                          <XAxis type="number" domain={[0, 'dataMax']} tick={{ fill: '#a49b92', fontSize: 10 }} />
                          <YAxis dataKey="name" type="category" width={96} tick={{ fill: '#a49b92', fontSize: 10 }} />
                          <Tooltip
                            formatter={(value) => [`${value}%`, '出现比例']}
                            contentStyle={{ background: '#000000', border: '1px solid rgba(228,181,146,0.35)', borderRadius: 0 }}
                            labelStyle={{ color: '#fff3ea' }}
                          />
                          <Bar dataKey="percentage" fill="#e4b592" radius={[0, 0, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="emerging-empty-state">该岗位没有可绘制的百分比字段，技术词仍可在上方查看。</div>
                    )}
                  </div>

                  <div className="archive-panel chart-archive-panel glass rounded-2xl p-6">
                    <FrameCorners />
                    <h3 className="font-outfit font-bold text-base text-[var(--text)] mb-1">
                      <RiseOutlined /> 行业 JD 覆盖
                    </h3>
                    <p className="text-xs text-[var(--text-dim)] mb-4">来自新岗位定义表的行业分布汇总</p>
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart data={industryChart} layout="vertical" margin={{ left: 12, right: 18 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,243,234,0.1)" />
                        <XAxis type="number" tick={{ fill: '#a49b92', fontSize: 10 }} />
                        <YAxis dataKey="name" type="category" width={96} tick={{ fill: '#a49b92', fontSize: 10 }} />
                        <Tooltip
                          formatter={(value) => [formatNumber(Number(value)), 'JD 数']}
                          contentStyle={{ background: '#000000', border: '1px solid rgba(228,181,146,0.35)', borderRadius: 0 }}
                          labelStyle={{ color: '#fff3ea' }}
                        />
                        <Bar dataKey="jdCount" fill="#dad0c8" radius={[0, 0, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </>
            ) : (
              <div className="archive-panel glass emerging-empty-detail">
                <FrameCorners />
                <DatabaseOutlined />
                <strong>没有可展示的岗位定义</strong>
                <span>请清空筛选条件，或检查后端和本地数据快照是否已生成。</span>
              </div>
            )}
          </div>
        </div>

        <div className="emerging-source-footer">
          <span><DatabaseOutlined /> SOURCE SNAPSHOT / {snapshot?.version ?? 'LOADING'}</span>
          <span>{summary?.averageJdPerDefinition ?? 0} JD / DEFINITION</span>
          <span>原始文件：新岗位定义.xlsx + 新岗位定义_技术词.xlsx</span>
        </div>
      </div>
    </div>
  )
}
