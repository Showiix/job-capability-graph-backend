import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import {
  BarChartOutlined,
  FireOutlined,
  LineChartOutlined,
  RiseOutlined,
  SafetyCertificateOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'
import { fetchGraphData, fetchGraphStats, fetchGraphTrends } from '../services/graphApi'

// Mock 新兴岗位数据
const EMERGING_JOBS = [
  {
    id: 'ej1',
    name: 'AIGC 算法工程师',
    category: 'AI/算法',
    trend: '上升',
    growth: '+285%',
    monthlyJobs: 142,
    avgSalary: '30-50K',
    isNew: true,
    keySkills: ['Stable Diffusion', 'DALL-E', 'ControlNet', 'LoRA', 'Prompt Engineering'],
    description: '负责生成式 AI 模型的研发和优化，包括文生图、图生图、视频生成等',
    confidence: 92,
  },
  {
    id: 'ej2',
    name: 'LLM 应用工程师',
    category: '大模型应用',
    trend: '上升',
    growth: '+198%',
    monthlyJobs: 256,
    avgSalary: '25-45K',
    isNew: true,
    keySkills: ['LangChain', 'RAG', 'Agent', 'Prompt 工程', 'Vector DB'],
    description: '基于大语言模型开发智能应用，构建 Agent 系统和知识库问答',
    confidence: 95,
  },
  {
    id: 'ej3',
    name: '云网智能运维员',
    category: '运维/云计算',
    trend: '上升',
    growth: '+156%',
    monthlyJobs: 89,
    avgSalary: '20-35K',
    isNew: true,
    keySkills: ['Kubernetes', 'Prometheus', 'AIOps', '自动化运维', 'ServiceMesh'],
    description: '利用 AI 技术进行智能运维，实现故障预测和自动修复',
    confidence: 88,
  },
  {
    id: 'ej4',
    name: '数字孪生工程师',
    category: '工业/物联网',
    trend: '上升',
    growth: '+124%',
    monthlyJobs: 67,
    avgSalary: '25-40K',
    isNew: true,
    keySkills: ['Unity3D', 'UE5', '物联网', '3D建模', '仿真技术'],
    description: '构建物理实体的数字副本，实现虚实映射和预测性维护',
    confidence: 85,
  },
  {
    id: 'ej5',
    name: '区块链开发工程师',
    category: '区块链/Web3',
    trend: '稳定',
    growth: '+45%',
    monthlyJobs: 134,
    avgSalary: '30-55K',
    isNew: false,
    keySkills: ['Solidity', 'Web3.js', '智能合约', 'DeFi', 'NFT'],
    description: '开发区块链应用和智能合约，构建去中心化系统',
    confidence: 78,
  },
  {
    id: 'ej6',
    name: '量子计算工程师',
    category: '前沿科技',
    trend: '上升',
    growth: '+89%',
    monthlyJobs: 23,
    avgSalary: '40-70K',
    isNew: true,
    keySkills: ['Qiskit', '量子算法', '量子电路', 'Python', '线性代数'],
    description: '研究和开发量子算法，探索量子计算在实际场景的应用',
    confidence: 72,
  },
]

/* Legacy demo data retained only as migration reference; live charts use /jd-graph/trends. */
const SKILL_TIMELINE = [
  { month: '2025-08', RAG: 45, LangChain: 32, Agent: 28, 'Prompt工程': 38 },
  { month: '2025-09', RAG: 68, LangChain: 52, Agent: 41, 'Prompt工程': 55 },
  { month: '2025-10', RAG: 95, LangChain: 78, Agent: 63, 'Prompt工程': 72 },
  { month: '2025-11', RAG: 128, LangChain: 105, Agent: 89, 'Prompt工程': 98 },
  { month: '2025-12', RAG: 165, LangChain: 142, Agent: 118, 'Prompt工程': 125 },
  { month: '2026-01', RAG: 198, LangChain: 178, Agent: 156, 'Prompt工程': 152 },
  { month: '2026-02', RAG: 234, LangChain: 215, Agent: 189, 'Prompt工程': 183 },
]

const HOT_SKILLS = [
  { name: 'LangChain', count: 342, growth: '+185%', level: '前沿', color: '#e4b592' },
  { name: 'RAG', count: 298, growth: '+168%', level: '前沿', color: '#e4b592' },
  { name: 'Prompt 工程', count: 256, growth: '+145%', level: '核心', color: '#ee1212' },
  { name: 'Agent 系统', count: 234, growth: '+132%', level: '前沿', color: '#e4b592' },
  { name: 'Vector DB', count: 189, growth: '+98%', level: '核心', color: '#ee1212' },
  { name: 'Stable Diffusion', count: 167, growth: '+215%', level: '前沿', color: '#e4b592' },
  { name: 'Fine-tuning', count: 145, growth: '+76%', level: '核心', color: '#ee1212' },
  { name: 'RLHF', count: 123, growth: '+112%', level: '前沿', color: '#e4b592' },
]

export default function EmergingJobsPage() {
  void SKILL_TIMELINE
  void HOT_SKILLS
  const [jobs, setJobs] = useState(EMERGING_JOBS)
  const [selectedJob, setSelectedJob] = useState(EMERGING_JOBS[0])
  const [filterTrend, setFilterTrend] = useState<'all' | '上升' | '稳定'>('all')
  const [sortBy, setSortBy] = useState<'growth' | 'jobs' | 'salary'>('growth')
  const [stats, setStats] = useState<Record<string, any> | null>(null)
  const [trends, setTrends] = useState<{ timeline: any[]; hot_skills: any[] } | null>(null)

  useEffect(() => {
    void fetchGraphStats().then(setStats).catch(() => undefined)
    void fetchGraphTrends().then(setTrends).catch(() => undefined)
    void fetchGraphData().then((graph) => {
      const live = graph.stars.filter((star) => star.isEmerging).map((star) => ({
        id: star.id,
        name: star.label,
        category: star.domain ?? '岗位能力',
        trend: '上升' as const,
        growth: `+${Math.max(1, star.sources ?? 1)}%`,
        monthlyJobs: star.jobCount ?? star.sources ?? 0,
        avgSalary: '待补充',
        isNew: true,
        keySkills: star.requiredSkills ?? [],
        description: `${star.label} 的实时岗位与技能画像`,
        confidence: 0,
      }))
      if (live.length) { setJobs(live); setSelectedJob(live[0]) }
    }).catch(() => undefined)
  }, [])

  const filteredJobs = jobs.filter((job) => filterTrend === 'all' || job.trend === filterTrend)

  const sortedJobs = [...filteredJobs].sort((a, b) => {
    if (sortBy === 'growth') return parseInt(b.growth) - parseInt(a.growth)
    if (sortBy === 'jobs') return b.monthlyJobs - a.monthlyJobs
    return 0
  })

  const getTrendColor = (trend: string) => {
    return trend === '上升' ? '#ee1212' : '#e4b592'
  }

  return (
    <div className="page-shell page-shell--emerging min-h-screen pt-14">
      <div className="page-shell__inner max-w-7xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive">
          <FrameCorners />
          <div className="page-head__icon">
            <RiseOutlined />
          </div>
          <div className="page-head__copy">
            <div className="page-head__eyebrow">Market radar / emerging roles</div>
            <h1 className="page-head__title">新兴岗位发现</h1>
            <p className="page-head__desc">追踪岗位增速、技能热度和需求置信度，提前识别新职业方向。</p>
          </div>
        </div>

        {/* Stats cards */}
        <div className="emerging-stats mb-8">
          {[
            { label: '岗位类别', value: String(stats?.total_categories ?? '—'), suffix: '类', color: '#e4b592' },
            { label: '岗位总量', value: String(stats?.total_jobs ?? '—'), suffix: '个', color: '#ee1212' },
            { label: '技能总量', value: String(stats?.total_skills ?? '—'), suffix: '项', color: '#fff3ea' },
            { label: '新兴技能', value: String(stats?.emerging_skills ?? '—'), suffix: '项', color: '#dad0c8' },
          ].map((stat, index) => (
            <div
              key={stat.label}
              className={`metric-card archive-metric emerging-stat ${index === 0 ? 'emerging-stat--primary' : ''} animate-fade-up`}
              style={{ '--accent': stat.color } as CSSProperties}
            >
              <div className="metric-card__label">{stat.label}</div>
              <div className="metric-card__value" style={{ color: stat.color }}>
                {stat.value}
                <span className="text-base ml-1">{stat.suffix}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="emerging-workspace-grid">
          {/* Left: Job list */}
          <div className="emerging-job-rail">
            <div className="archive-panel glass rounded-2xl p-4">
              <FrameCorners />
              <div className="flex justify-between items-center mb-4">
                <h2 className="font-outfit font-bold text-base text-[var(--text)]">岗位列表</h2>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as any)}
                  className="bg-[rgba(0,0,0,0.44)] border border-[var(--border)] px-2 py-1 text-xs text-[var(--text)] outline-none"
                >
                  <option value="growth">按增长率</option>
                  <option value="jobs">按岗位数</option>
                  <option value="salary">按薪资</option>
                </select>
              </div>

              {/* Filter buttons */}
              <div className="flex gap-2 mb-4">
                {(['all', '上升', '稳定'] as const).map((f) => (
                  <button
                    key={f}
                    className={`btn btn-sm ${filterTrend === f ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => setFilterTrend(f)}
                  >
                    {f === 'all' ? '全部' : f}
                  </button>
                ))}
              </div>

              <div className="emerging-job-list space-y-2 max-h-[600px] overflow-y-auto pr-2">
                {sortedJobs.map((job) => (
                  <div
                    key={job.id}
                    className={`archive-row market-archive-row glass rounded-xl p-3 cursor-pointer transition-all ${
                      selectedJob.id === job.id ? 'ring-2 ring-space-cyan' : ''
                    }`}
                    onClick={() => setSelectedJob(job)}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1">
                        <div className="font-outfit font-bold text-sm text-[var(--text)] mb-1">
                          {job.isNew && <RiseOutlined className="text-[#ee1212] mr-1" />}
                          {job.name}
                        </div>
                        <div className="text-xs text-[var(--text-dim)]">{job.category}</div>
                      </div>
                      <div className="text-right">
                        <div
                          className="font-jetbrains font-bold text-sm"
                          style={{ color: getTrendColor(job.trend) }}
                        >
                          {job.growth}
                        </div>
                        <div className="text-[10px] text-[var(--text-dim)]">{job.monthlyJobs} 个职位</div>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {job.keySkills.slice(0, 3).map((skill) => (
                      <span key={skill} className="text-[10px] px-1.5 py-0.5 bg-[rgba(228,181,146,0.08)] text-[#e4b592] border border-[rgba(228,181,146,0.28)]">
                          {skill}
                        </span>
                      ))}
                      {job.keySkills.length > 3 && (
                        <span className="text-[10px] text-[var(--text-dim)]">+{job.keySkills.length - 3}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Details and charts */}
          <div className="emerging-insight-stack space-y-6">
            {/* Job detail */}
            <div className="archive-panel glass rounded-2xl p-6">
              <FrameCorners />
              <div className="flex justify-between items-start mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    {selectedJob.isNew && <RiseOutlined className="text-xl text-[#ee1212]" />}
                    <h2 className="font-outfit font-extrabold text-2xl text-[var(--text)]">{selectedJob.name}</h2>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-[var(--text-dim)]">
                    <span><TagsOutlined /> {selectedJob.category}</span>
                    <span><BarChartOutlined /> {selectedJob.avgSalary}</span>
                    <span><LineChartOutlined /> {selectedJob.monthlyJobs} 个职位/月</span>
                  </div>
                </div>
                <div className="text-right">
                  <div
                    className="font-jetbrains font-black text-3xl mb-1"
                    style={{ color: getTrendColor(selectedJob.trend) }}
                  >
                    {selectedJob.growth}
                  </div>
                  <div className="flex items-center gap-1 text-xs">
                    <span className="text-[var(--text-dim)]">置信度</span>
                    <span className="badge-conf">{selectedJob.confidence}%</span>
                  </div>
                </div>
              </div>

              <p className="text-sm text-[var(--text-dim)] mb-4 leading-relaxed">{selectedJob.description}</p>

              <div>
                <div className="text-sm font-medium text-[var(--text)] mb-2"><SafetyCertificateOutlined /> 核心技能要求</div>
                <div className="flex flex-wrap gap-2">
                  {selectedJob.keySkills.map((skill) => (
                    <span key={skill} className="tag tag-purple">
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Skill timeline chart */}
            <div className="archive-panel chart-archive-panel glass rounded-2xl p-6">
              <FrameCorners />
              <h3 className="font-outfit font-bold text-base text-[var(--text)] mb-4"><LineChartOutlined /> 技能需求趋势（近7个月）</h3>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={trends?.timeline ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,243,234,0.1)" />
                  <XAxis dataKey="month" tick={{ fill: '#a49b92', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#a49b92', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      background: '#000000',
                      border: '1px solid rgba(228,181,146,0.35)',
                      borderRadius: 0,
                    }}
                    labelStyle={{ color: '#fff3ea' }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {(trends?.hot_skills ?? []).slice(0, 4).map((skill, index) => <Line key={skill.name} type="monotone" dataKey={skill.name} stroke={['#e4b592', '#fff3ea', '#dad0c8', '#ee1212'][index]} strokeWidth={2} dot={{ r: 3 }} />)}
                </LineChart>
              </ResponsiveContainer>
              {trends && trends.timeline.length === 0 && <div className="text-xs text-[var(--text-dim)] text-center mt-[-130px] relative">暂无带发布时间的历史 JD，无法生成近 7 个月趋势</div>}
            </div>

            {/* Hot skills */}
            <div className="archive-panel chart-archive-panel glass rounded-2xl p-6">
              <FrameCorners />
              <h3 className="font-outfit font-bold text-base text-[var(--text)] mb-4"><FireOutlined /> 热门技能排行</h3>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={trends?.hot_skills ?? []} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,243,234,0.1)" />
                  <XAxis type="number" tick={{ fill: '#a49b92', fontSize: 11 }} />
                  <YAxis dataKey="name" type="category" tick={{ fill: '#a49b92', fontSize: 11 }} width={100} />
                  <Tooltip
                    contentStyle={{
                      background: '#000000',
                      border: '1px solid rgba(228,181,146,0.35)',
                      borderRadius: 0,
                    }}
                    labelStyle={{ color: '#fff3ea' }}
                  />
                  <Bar dataKey="count" fill="#e4b592" radius={[0, 0, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              {trends && trends.hot_skills.length === 0 && <div className="text-xs text-[var(--text-dim)] text-center mt-[-145px] relative">暂无可统计的技能需求数据</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
