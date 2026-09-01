import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer } from 'recharts'
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudUploadOutlined,
  CompassOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  FundProjectionScreenOutlined,
  LoadingOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  RocketOutlined,
  SwapOutlined,
  TrophyOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'
import { GraphScene3D } from '../components/GraphScene3D'
import FadeContent from '../components/reactbits/FadeContent/FadeContent'
import CountUp from '../components/reactbits/CountUp/CountUp'
import { useAuth } from '../context/AuthContext'
import { fetchGraphData } from '../services/graphApi'
import {
  confirmResumeProfile,
  createResumeRevision,
  createGrowthPath,
  createJobRecommendations,
  createResume,
  getProcessingRun,
  getProcessingRunResult,
  retryProcessingRun,
  cancelProcessingRun,
  getRecommendationDetail,
  getResume,
  getResumeProfile,
  type GrowthPathRead,
  type MatchResultListItem,
  type ProcessingRunResponse,
  type RecommendationCreateResponse,
  type RecommendationDetailResponse,
  type ResumeProcessingResult,
  type ResumeProfileDetail,
  type ResumeSkillRecord,
} from '../services/resumeWorkflowApi'
import type { GraphData, Planet, Star } from '../types/graph'
import { findGraphStarForRole } from '../utils/graphRoleMatch'

type Step = 0 | 1 | 2 | 3
type ActiveTab = 'radar' | 'skills' | 'graph' | 'path'
type UploadState = 'idle' | 'uploading' | 'processing' | 'ready' | 'failed'

const APPLICANT_STEPS = ['上传简历', '技能确认', '岗位匹配', '学习路径']
const MAX_RESUME_BYTES = 20 * 1024 * 1024
const TOP_JOB_COUNT = 5

const STAGE_LABELS: Record<string, string> = {
  upload: '上传文件',
  extract_text: '提取文字',
  redact_text: '脱敏处理',
  call_llm: '调用 DeepSeek',
  validate_response: '校验结构化结果',
  validate_evidence: '定位原文证据',
  map_capabilities: '映射能力图谱',
  persist_profile: '保存简历画像',
  completed: '解析完成',
}

const EDUCATION_LABELS: Record<string, string> = {
  high_school: '高中',
  associate: '专科',
  bachelor: '本科',
  master: '硕士',
  doctor: '博士',
  other: '其他',
  unknown: '未知',
}

const EVIDENCE_LABELS: Record<string, string> = {
  mention: '简历提及',
  project: '项目证据',
  work: '工作证据',
}

const PROFICIENCY_LABELS: Record<string, string> = {
  beginner: '初级',
  intermediate: '中级',
  advanced: '高级',
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function apiErrorMessage(error: unknown) {
  const value = error as { apiCode?: string; apiMessage?: string; message?: string; code?: string }
  if (value.apiCode === 'GRAPH_VERSION_NOT_PUBLISHED') {
    return '系统岗位图谱尚未初始化，请联系管理员执行 Catalog / Graph 初始化；这不是当前账号的权限问题。'
  }
  if (value.code === 'ECONNABORTED' || /timeout/i.test(value.message ?? '')) {
    return '后端生成耗时超过请求时限（大模型响应较慢），请点击重试；多次失败请稍后再试'
  }
  return value.apiMessage || value.message || '请求失败，请稍后重试'
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

function toPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return 0
  return clampPercent(value <= 1 ? value * 100 : value)
}

function stageLabel(stage: string | null | undefined) {
  if (!stage) return '等待任务'
  return STAGE_LABELS[stage] || stage
}

function skillName(skill: ResumeSkillRecord) {
  return skill.capability_name || skill.raw_name || skill.normalized_name
}

function evidenceLabel(value: string | null | undefined) {
  return value ? EVIDENCE_LABELS[value] || value : '未标注'
}

function proficiencyLabel(value: string | null | undefined) {
  return value ? PROFICIENCY_LABELS[value] || value : '未判断'
}

function educationLabel(value: string | null | undefined) {
  return value ? EDUCATION_LABELS[value] || value : '—'
}

function formatMonths(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  if (value < 12) return `${value} 个月`
  const years = Math.floor(value / 12)
  const months = value % 12
  return months ? `${years} 年 ${months} 个月` : `${years} 年`
}

function dateRange(item: Record<string, any>) {
  const start = typeof item.start_month === 'string' ? item.start_month : '未知'
  if (item.is_current) return `${start} - 至今`
  const end = typeof item.end_month === 'string' ? item.end_month : '未知'
  return `${start} - ${end}`
}

function itemText(item: Record<string, any>, keys: string[]) {
  for (const key of keys) {
    if (typeof item[key] === 'string' && item[key].trim()) return item[key]
  }
  return '未命名条目'
}

function matchLevelLabel(value: MatchResultListItem['match_level']) {
  if (value === 'high') return '高匹配'
  if (value === 'medium') return '中匹配'
  return '低匹配'
}

function matchLevelColor(value: MatchResultListItem['match_level']) {
  if (value === 'high') return '#dad0c8'
  if (value === 'medium') return '#e4b592'
  return '#8f877f'
}

function radarData(result: MatchResultListItem | null) {
  if (!result) return []
  const scores = result.dimension_scores
  return [
    { axis: '必备技能', score: toPercent(scores.required_skill_coverage.score) },
    { axis: '加分技能', score: toPercent(scores.bonus_skill_coverage.score) },
    { axis: '证据质量', score: toPercent(scores.skill_evidence_quality.score) },
    { axis: '经验', score: toPercent(scores.experience.score) },
    { axis: '学历', score: toPercent(scores.education.score) },
  ]
}

function validateResumeFile(file: File) {
  if (!/\.(pdf|docx|jpe?g|png)$/i.test(file.name)) return '仅支持 PDF、Word、JPG 或 PNG 简历'
  if (file.size > MAX_RESUME_BYTES) return '简历文件不能超过 20 MB'
  return null
}

function Ring({ v, size = 64, color = '#e4b592' }: { v: number; size?: number; color?: string }) {
  const r = (size - 8) / 2
  const c = 2 * Math.PI * r
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,243,234,0.12)" strokeWidth="5" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="5"
          strokeDasharray={`${(clampPercent(v) / 100) * c} ${c}`}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color})` }}
        />
      </svg>
      <div className="absolute font-jetbrains font-bold" style={{ fontSize: size * 0.19, color }}>
        {clampPercent(v)}%
      </div>
    </div>
  )
}

function RocketLoader({ progress, stage }: { progress: number; stage: string | null }) {
  const steps = [
    { min: 1, label: '上传文件' },
    { min: 10, label: '提取文字' },
    { min: 40, label: '调用 DeepSeek' },
    { min: 75, label: '校验证据' },
    { min: 95, label: '保存画像' },
  ]
  const currentProgress = clampPercent(progress)

  return (
    <div className="text-center py-10">
      <div className="relative h-24 flex items-center justify-center">
        <div className="rocket-badge animate-rocket-rise">
          <RocketOutlined />
        </div>
        <div
          className="absolute bottom-2 left-1/2 -translate-x-1/2 w-5 h-6 rounded-b-full"
          style={{
            background: 'linear-gradient(180deg, #e4b592, #ee1212aa, transparent)',
            animation: 'exhaust 0.3s infinite',
            transformOrigin: 'top center',
          }}
        />
      </div>

      <div className="font-jetbrains text-[10px] text-[#e4b592] uppercase tracking-[0.16em] mb-4">
        {stageLabel(stage)}
      </div>
      <div className="mb-5">
        {steps.map((item) => (
          <div
            key={item.label}
            className="flex items-center gap-2 mb-2 justify-center transition-opacity duration-300"
            style={{ opacity: currentProgress >= item.min ? 1 : 0.25 }}
          >
            <div
              className="w-2.5 h-2.5 flex-shrink-0"
              style={
                currentProgress >= item.min
                  ? { background: '#dad0c8' }
                  : { border: '1px solid rgba(255,243,234,0.3)' }
              }
            />
            <span className="text-[13px] font-inter" style={{ color: currentProgress >= item.min ? '#fff3ea' : '#a49b92' }}>
              {item.label}
            </span>
            {currentProgress >= item.min && <span className="text-[#dad0c8] text-xs">✓</span>}
          </div>
        ))}
      </div>

      <div className="max-w-sm mx-auto">
        <div className="prog-track h-1.5">
          <div
            className="prog-fill transition-all duration-150 ease-linear"
            style={{ width: `${currentProgress}%`, background: 'linear-gradient(90deg, #ee1212, #e4b592)' }}
          />
        </div>
        <div className="flex justify-between mt-1.5">
          <span className="font-jetbrains text-[11px] text-[#e4b592]">{currentProgress}%</span>
          <span className="text-[11px] text-[var(--text-dim)]">真实任务进度</span>
        </div>
      </div>
    </div>
  )
}

export default function ApplicantFlowPage() {
  const navigate = useNavigate()
  const { user, loading: authLoading, sessionError, ensureSession } = useAuth()
  const [step, setStep] = useState<Step>(0)
  const [uploading, setUploading] = useState(false)
  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [progress, setProgress] = useState(0)
  const [drag, setDrag] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [currentRun, setCurrentRun] = useState<ProcessingRunResponse | null>(null)
  const [resumeRunResult, setResumeRunResult] = useState<ResumeProcessingResult | null>(null)
  const [resumeProfile, setResumeProfile] = useState<ResumeProfileDetail | null>(null)
  const [resumeContentUrl, setResumeContentUrl] = useState<string | null>(null)
  const [workflowError, setWorkflowError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<ActiveTab>('radar')
  const [recommendationLoading, setRecommendationLoading] = useState(false)
  const [recommendations, setRecommendations] = useState<RecommendationCreateResponse | null>(null)
  const [selectedJobRoleId, setSelectedJobRoleId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [selectedMatchDetail, setSelectedMatchDetail] = useState<RecommendationDetailResponse | null>(null)
  const [jobGraphData, setJobGraphData] = useState<GraphData | null>(null)
  const [jobGraphLoading, setJobGraphLoading] = useState(false)
  const [jobGraphError, setJobGraphError] = useState<string | null>(null)
  const [selectedGraphStar, setSelectedGraphStar] = useState<Star | null>(null)
  const [selectedGraphPlanet, setSelectedGraphPlanet] = useState<Planet | null>(null)
  const [growthLoading, setGrowthLoading] = useState(false)
  const [growthError, setGrowthError] = useState<string | null>(null)
  const [growthPath, setGrowthPath] = useState<GrowthPathRead | null>(null)
  const [growthPathKey, setGrowthPathKey] = useState<string | null>(null)
  const [showAllJobs, setShowAllJobs] = useState(false)
  const [jobGraphRetry, setJobGraphRetry] = useState(0)
  const jobGraphAttemptedRef = useRef(false)
  const [editedSkills, setEditedSkills] = useState('')
  const [revisionSaving, setRevisionSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const profilePayload = resumeProfile?.profile ?? {}
  const educations = Array.isArray(profilePayload.educations) ? profilePayload.educations : []
  const experiences = Array.isArray(profilePayload.experiences) ? profilePayload.experiences : []
  const projects = Array.isArray(profilePayload.projects) ? profilePayload.projects : []
  const summary = typeof profilePayload.summary === 'string' && profilePayload.summary.trim() ? profilePayload.summary : '后端暂未返回摘要'
  const jobItems = recommendations?.results?.items ?? []
  const visibleJobs = showAllJobs ? jobItems : jobItems.slice(0, TOP_JOB_COUNT)
  const selectedResult = useMemo(
    () => recommendations?.results.items.find((item) => item.job_role_id === selectedJobRoleId) ?? null,
    [recommendations, selectedJobRoleId],
  )
  const selectedGrowthKey = recommendations && selectedJobRoleId ? `${recommendations.run.id}:${selectedJobRoleId}` : null
  const currentGrowthPath = growthPath && growthPathKey === selectedGrowthKey ? growthPath : null
  const selectedRadarData = useMemo(() => radarData(selectedResult), [selectedResult])
  const matchedCapabilities = selectedMatchDetail?.matched_capabilities ?? []
  const missingCapabilities = selectedMatchDetail?.missing_capabilities ?? []
  const missingRequired = missingCapabilities.filter((item) => item.requirement_type === 'required')
  const missingBonus = missingCapabilities.filter((item) => item.requirement_type === 'bonus')
  const selectedRoleGraphPath = useMemo(() => {
    if (!selectedResult) return '/graph'
    const params = new URLSearchParams()
    params.set('job', selectedResult.job_role.canonical_name)
    params.set('jobId', selectedResult.job_role_id)
    return `/graph?${params.toString()}`
  }, [selectedResult])
  const selectedGraphMatch = useMemo(() => {
    if (!jobGraphData || !selectedResult) return null
    return findGraphStarForRole(jobGraphData.stars, {
      jobRoleId: selectedResult.job_role_id,
      roleId: selectedResult.job_role.id,
      canonicalName: selectedResult.job_role.canonical_name,
      domainName: selectedResult.job_role.domain?.name,
      definitionPayload: selectedMatchDetail?.job_role?.definition_payload,
    })
  }, [jobGraphData, selectedMatchDetail?.job_role?.definition_payload, selectedResult])
  const selectedJobGraphData = useMemo<GraphData | null>(() => {
    if (!jobGraphData || !selectedGraphMatch) return null
    return {
      stars: [selectedGraphMatch],
      planets: jobGraphData.planets.filter((planet) => planet.starId === selectedGraphMatch.id),
      metadata: jobGraphData.metadata,
    }
  }, [jobGraphData, selectedGraphMatch])
  const graphFocusLabel = selectedGraphPlanet
    ? `${selectedGraphPlanet.label} / ${selectedGraphPlanet.isRequired ? '必备能力' : '加分能力'}`
    : selectedGraphStar?.label ?? selectedGraphMatch?.label ?? selectedResult?.job_role.canonical_name ?? '等待选择岗位'

  useEffect(() => {
    if (!recommendations?.run.id || !selectedJobRoleId) {
      setSelectedMatchDetail(null)
      return
    }

    let alive = true
    setDetailLoading(true)
    setDetailError(null)
    setSelectedMatchDetail(null)
    setGrowthError(null)
    setGrowthPath(null)
    setGrowthPathKey(null)

    getRecommendationDetail(recommendations.run.id, selectedJobRoleId)
      .then((detail) => {
        if (!alive) return
        setSelectedMatchDetail(detail)
      })
      .catch((error) => {
        if (!alive) return
        setDetailError(apiErrorMessage(error))
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })

    return () => {
      alive = false
    }
  }, [recommendations?.run.id, selectedJobRoleId])

  useEffect(() => {
    // 用 ref 记录“只自动尝试一次”：deps 不含 loading/attempted 状态，
    // 避免 effect 内同步 setState 触发 cleanup 使 finally 无法复位 loading
    if (step < 2 || jobGraphData || jobGraphAttemptedRef.current) return

    jobGraphAttemptedRef.current = true
    let alive = true
    setJobGraphLoading(true)
    setJobGraphError(null)

    Promise.race([
      fetchGraphData(),
      new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error('岗位图谱读取超时，请稍后重试')), 5_000)),
    ])
      .then((data) => {
        if (!alive) return
        setJobGraphData(data)
      })
      .catch((error) => {
        if (!alive) return
        setJobGraphError(apiErrorMessage(error))
      })
      .finally(() => {
        if (alive) setJobGraphLoading(false)
      })

    return () => {
      alive = false
    }
  }, [step, jobGraphData, jobGraphRetry])

  useEffect(() => {
    setSelectedGraphStar(null)
    setSelectedGraphPlanet(null)
  }, [selectedJobRoleId])

  const resetAnalysisState = () => {
    setCurrentRun(null)
    setResumeRunResult(null)
    setResumeProfile(null)
    setResumeContentUrl(null)
    setRecommendations(null)
    setSelectedJobRoleId(null)
    setSelectedMatchDetail(null)
    setGrowthPath(null)
    setGrowthPathKey(null)
    setGrowthError(null)
    setDetailError(null)
    setSelectedGraphStar(null)
    setSelectedGraphPlanet(null)
    setShowAllJobs(false)
    jobGraphAttemptedRef.current = false
    setJobGraphData(null)
    setJobGraphError(null)
    setActiveTab('radar')
  }

  const reloadJobGraph = () => {
    jobGraphAttemptedRef.current = false
    setJobGraphError(null)
    setJobGraphRetry((n) => n + 1)
  }

  const startUpload = async (file: File) => {
    if (uploading) return
    const validationError = validateResumeFile(file)
    if (validationError) {
      setWorkflowError(validationError)
      return
    }
    const session = user ?? await ensureSession()
    if (!session) {
      setWorkflowError('浏览器任务通道未建立，请确认后端服务已启动后重试')
      return
    }

    resetAnalysisState()
    setStep(0)
    setSelectedFile(file)
    setUploading(true)
    setUploadState('uploading')
    setWorkflowError(null)
    setProgress(2)

    try {
      const created = await createResume(file, file.name, (uploadProgress) => {
        setProgress(Math.max(2, Math.min(30, Math.round(uploadProgress * 0.3))))
      })
      setUploadState('processing')
      setProgress(10)

      let latestRun: ProcessingRunResponse | null = null
      for (let attempt = 0; attempt < 120; attempt += 1) {
        latestRun = await getProcessingRun(created.run_id)
        setCurrentRun(latestRun)
        setProgress(clampPercent(latestRun.progress_percent))

        if (latestRun.status === 'completed') {
          const result = await getProcessingRunResult(created.run_id)
          const profile = await getResumeProfile(created.resource_id, result.profile_version)
          const resume = await getResume(created.resource_id)
          setResumeRunResult(result)
          setResumeProfile(profile)
          setResumeContentUrl(resume.file.content_url)
          setUploadState('ready')
          setProgress(100)
          setStep(1)
          return
        }

        if (latestRun.status === 'failed' || latestRun.status === 'cancelled' || latestRun.status === 'enqueue_failed') {
          throw new Error(latestRun.error_message || '简历解析失败')
        }

        await sleep(2_000)
      }

      throw new Error('简历解析超时，请稍后重试')
    } catch (error) {
      setUploadState('failed')
      setWorkflowError(apiErrorMessage(error))
    } finally {
      setUploading(false)
    }
  }

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) void startUpload(file)
    event.target.value = ''
  }

  const retryCurrentRun = async () => {
    if (!currentRun) return
    setWorkflowError(null)
    try {
      const next = await retryProcessingRun(currentRun.id)
      setCurrentRun(next)
      setUploadState('processing')
      setUploading(true)
      setProgress(2)
      setWorkflowError('已创建重试任务，请重新等待解析完成')
    } catch (error) {
      setWorkflowError(apiErrorMessage(error))
    } finally {
      setUploading(false)
    }
  }

  const cancelCurrentRun = async () => {
    if (!currentRun) return
    try {
      const next = await cancelProcessingRun(currentRun.id)
      setCurrentRun(next)
      setUploadState('failed')
      setWorkflowError('任务已取消')
    } catch (error) {
      setWorkflowError(apiErrorMessage(error))
    }
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDrag(false)
    if (!user || authLoading || uploading) return
    const file = event.dataTransfer.files[0]
    if (file) void startUpload(file)
  }

  const handleConfirmAndRecommend = async () => {
    if (!resumeProfile) return
    setRecommendationLoading(true)
    setWorkflowError(null)
    try {
      const confirmedProfile =
        resumeProfile.status === 'confirmed'
          ? resumeProfile
          : await confirmResumeProfile(resumeProfile.resume_id, resumeProfile.version_no)
      setResumeProfile(confirmedProfile)
      const created = await createJobRecommendations(confirmedProfile.resume_id)
      const items = created?.results?.items
      if (!Array.isArray(items)) throw new Error('岗位推荐返回格式无效')
      setRecommendations(created)
      setSelectedJobRoleId(items[0]?.job_role_id ?? null)
      setShowAllJobs(false)
      setActiveTab('radar')
      setStep(2)
    } catch (error) {
      setWorkflowError(apiErrorMessage(error))
    } finally {
      setRecommendationLoading(false)
    }
  }

  const saveProfileRevision = async () => {
    if (!resumeProfile) return
    const skills = editedSkills.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
    if (!skills.length) return
    setRevisionSaving(true)
    try {
      const revision = await createResumeRevision(resumeProfile.resume_id, resumeProfile.version_no, skills)
      setResumeProfile(revision)
      setWorkflowError('人工修订草稿已保存，请再次确认画像')
    } catch (error) {
      setWorkflowError(apiErrorMessage(error))
    } finally {
      setRevisionSaving(false)
    }
  }

  const handleCreateGrowthPath = async () => {
    if (!recommendations || !selectedJobRoleId) return
    const key = `${recommendations.run.id}:${selectedJobRoleId}`
    if (growthPath && growthPathKey === key) {
      setActiveTab('path')
      setStep(3)
      return
    }

    setGrowthLoading(true)
    setGrowthError(null)
    setActiveTab('path')
    try {
      const created = await createGrowthPath(recommendations.run.id, selectedJobRoleId)
      setGrowthPath(created.growth_path)
      setGrowthPathKey(key)
      setStep(3)
    } catch (error) {
      setGrowthError(apiErrorMessage(error))
    } finally {
      setGrowthLoading(false)
    }
  }

  const statusTitle =
    uploadState === 'failed'
      ? '解析失败'
      : uploadState === 'ready'
        ? '画像已生成'
        : uploadState === 'processing'
          ? '后端处理中'
          : uploadState === 'uploading'
            ? '正在上传'
            : authLoading
              ? '准备浏览器任务通道'
              : user
                ? '等待输入'
                : '任务通道未建立'

  return (
    <div className="page-shell page-shell--applicant min-h-screen pt-14">
      <div className="page-shell__inner max-w-5xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive">
          <FrameCorners />
          <div className="page-head__icon">
            <FileSearchOutlined />
          </div>
          <div className="page-head__copy">
            <div className="page-head__eyebrow">Resume scan / profile analysis</div>
            <h1 className="page-head__title">简历评估</h1>
            <p className="page-head__desc">上传真实简历，调用后端 LLM 解析画像、推荐岗位并生成成长路径。</p>
          </div>
        </div>

        <div className="archive-panel glass rounded-2xl p-4 mb-7">
          <FrameCorners />
          {authLoading ? (
            <div className="flex items-center gap-3 text-[13px] text-[var(--text-dim)]">
              <LoadingOutlined />
              正在准备浏览器任务通道
            </div>
          ) : user ? (
            <div className="flex items-center gap-3 flex-wrap">
              <span className="tag tag-green">
                <CheckCircleOutlined />
                {user.username === 'guest_applicant' ? '免登录通道已准备' : '当前通道已准备'}
              </span>
              <span className="font-jetbrains text-[10px] text-[var(--text-dim)]">
                无需账号密码 · SESSION / READY
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2 text-[13px] text-[#ee1212]">
                <WarningOutlined />
                浏览器任务通道未建立
              </div>
              <span className="text-[12px] text-[var(--text-dim)]">
                {sessionError || '可以直接重试，无需输入账号和密码'}
              </span>
              <button className="btn btn-sm btn-ghost ml-auto" onClick={() => void ensureSession()}>
                <ReloadOutlined />
                重试
              </button>
            </div>
          )}
        </div>

        <div className="console-stepper archive-stepper mb-10">
          {APPLICANT_STEPS.map((label, i) => (
            <div key={label} className="console-stepper__item">
              <div
                className={`step-dot ${i < step ? 'step-done' : i === step ? 'step-active' : 'step-idle'}`}
                onClick={() => i < step && setStep(i as Step)}
                style={{ cursor: i < step ? 'pointer' : 'default' }}
              >
                {i < step ? '✓' : i + 1}
              </div>
              <div className="console-stepper__copy ml-2.5 flex-1 min-w-0">
                <div className="console-stepper__meta">STEP {String(i + 1).padStart(2, '0')}</div>
                <div
                  className="console-stepper__label font-inter font-semibold text-[13px]"
                  style={{ color: i === step ? 'var(--text)' : i < step ? '#dad0c8' : 'var(--text-dim)' }}
                >
                  {label}
                </div>
              </div>
              {i < 3 && (
                <div
                  className="console-stepper__line"
                  style={{ background: i < step ? 'linear-gradient(90deg,#dad0c8,#e4b592)' : 'var(--border)' }}
                />
              )}
            </div>
          ))}
        </div>

        {step === 0 && (
          <div className="applicant-upload-grid animate-fade-up">
            <div
              className={`console-dropzone archive-panel applicant-upload-panel glass rounded-2xl p-16 text-center transition-all duration-300 ${drag ? 'glass-bright' : ''}`}
              style={{
                border: drag ? '2px dashed #e4b592' : '2px dashed rgba(255,243,234,0.22)',
                boxShadow: drag ? '0 0 40px rgba(228,181,146,0.1)' : 'none',
                cursor: !uploading && user ? 'pointer' : 'default',
                opacity: authLoading ? 0.72 : 1,
              }}
              onDragOver={(event) => {
                event.preventDefault()
                if (uploading) return
                setDrag(true)
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={handleDrop}
              onClick={() => {
                if (!uploading && user) fileRef.current?.click()
              }}
            >
              <FrameCorners />
              {uploading ? (
                <RocketLoader progress={progress} stage={currentRun?.current_stage ?? 'upload'} />
              ) : (
                <>
                  <div className="dropzone-icon animate-float">
                    <CloudUploadOutlined />
                  </div>
                  <div className="font-outfit font-bold text-2xl text-[var(--text)] mb-2">
                    {selectedFile ? selectedFile.name : '上传候选人简历'}
                  </div>
                  <div className="text-[13px] text-[var(--text-dim)] mb-1.5">
                    拖拽文件或点击选择，进入后自动准备免登录任务通道
                  </div>
                  <div className="text-[11px] text-[#a49b92]">支持 PDF / Word / JPG / PNG · 最大 20 MB</div>
                  {workflowError && (
                    <div className="mt-5 mx-auto max-w-md border border-[rgba(238,18,18,0.45)] bg-[rgba(238,18,18,0.06)] px-3 py-2 text-left text-[12px] text-[#ee1212]">
                      <div className="flex items-center gap-2 font-semibold">
                        <WarningOutlined />
                        {workflowError}
                      </div>
                      {currentRun?.error_code && (
                        <div className="mt-1 font-jetbrains text-[10px] text-[rgba(238,18,18,0.78)]">
                          ERROR / {currentRun.error_code}
                        </div>
                      )}
                      <div className="mt-3 flex gap-2">
                        {currentRun?.status === 'failed' && <button className="btn btn-sm btn-primary" onClick={(event) => { event.stopPropagation(); void retryCurrentRun() }}><ReloadOutlined /> 重试任务</button>}
                        {currentRun && ['pending', 'running', 'cancel_requested'].includes(currentRun.status) && <button className="btn btn-sm btn-ghost" onClick={(event) => { event.stopPropagation(); void cancelCurrentRun() }}>取消任务</button>}
                      </div>
                    </div>
                  )}
                  <div className="mt-7 flex gap-3 justify-center">
                    <button
                      className="btn btn-md btn-primary"
                      disabled={uploading || authLoading || !user}
                      onClick={(event) => {
                        event.stopPropagation()
                        if (user) fileRef.current?.click()
                      }}
                    >
                      <FolderOpenOutlined />
                      选择文件
                    </button>
                    {workflowError && (
                      <button
                        className="btn btn-md btn-ghost"
                        onClick={(event) => {
                          event.stopPropagation()
                          setWorkflowError(null)
                          setCurrentRun(null)
                          setUploadState('idle')
                        }}
                      >
                        <ReloadOutlined />
                        重置
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
            <input ref={fileRef} type="file" className="hidden" accept=".pdf,.docx,.jpg,.jpeg,.png" disabled={authLoading || !user} onChange={handleFileSelect} />
            <aside className="applicant-scan-rail archive-panel glass">
              <FrameCorners />
              <div className="applicant-scan-rail__eyebrow">Real backend / async run</div>
              <h2>简历档案入口</h2>
              <p>上传后端将创建处理任务，完成后返回结构化简历画像。</p>
              <div className="applicant-scan-rail__status">
                <span className="applicant-scan-rail__status-line" />
                <div>
                  <strong>{statusTitle}</strong>
                  <span>{currentRun ? stageLabel(currentRun.current_stage) : selectedFile?.name || '结构化解析尚未启动'}</span>
                </div>
              </div>
              <dl className="applicant-scan-rail__facts">
                <div>
                  <dt>SESSION</dt>
                  <dd>{authLoading ? 'PREPARING' : user ? 'READY' : 'RETRY'}</dd>
                </div>
                <div>
                  <dt>RUN</dt>
                  <dd>{currentRun?.id.slice(0, 8) || 'WAIT'}</dd>
                </div>
                <div>
                  <dt>SKILLS</dt>
                  <dd>{resumeRunResult ? `${resumeRunResult.mapped_skill_count}/${resumeRunResult.unmapped_skill_count}` : 'PENDING'}</dd>
                </div>
              </dl>
            </aside>
          </div>
        )}

        {step === 1 && resumeProfile && (
          <div className="applicant-skill-grid animate-fade-up">
            {/* ── 左：AI 提取的技能（时间线卡片）──────────────── */}
            <section className="skill-board archive-panel glass rounded-2xl overflow-hidden">
              <FrameCorners />
              <div className="skill-board__bg" />
              <header className="skill-board__head">
                <div className="skill-board__kicker">
                  <span className="skill-board__kicker-dot" />
                  <span>Skill extraction report · AI 抽取报告</span>
                </div>
                <div className="skill-board__meta">
                  <strong className="skill-board__meta-num">{resumeProfile.skills.length}</strong>
                  <span>ITEMS</span>
                  <em>{resumeProfile.status.toUpperCase()}</em>
                </div>
              </header>

              {resumeProfile.skills.length ? (
                <ul className="skill-list">
                  {resumeProfile.skills.map((skill, i) => {
                    const mapped = skill.mapping_status === 'mapped'
                    const confidence = toPercent(skill.confidence)
                    return (
                      <li
                        key={skill.id}
                        className="skill-card"
                        style={{ animationDelay: `${Math.min(i, 12) * 50}ms` }}
                      >
                        <div className="skill-card__rail" aria-hidden>
                          <span className={`skill-card__dot ${mapped ? 'is-mapped' : 'is-unmapped'}`} />
                          {i < resumeProfile.skills.length - 1 && <span className="skill-card__line" />}
                        </div>

                        <div className="skill-card__body">
                          <header className="skill-card__head">
                            <div className="skill-card__name">
                              <span className={`skill-tag ${mapped ? 'skill-tag--mapped' : 'skill-tag--unmapped'}`}>
                                {skillName(skill)}
                              </span>
                              <span className={`skill-status-tag ${mapped ? 'is-mapped' : 'is-unmapped'}`}>
                                {mapped ? 'MAPPED · 已对齐图谱' : 'UNMAPPED · 待人工确认'}
                              </span>
                            </div>
                            <div className="skill-card__conf">
                              <span className="skill-card__conf-num">{confidence}</span>
                              <span className="skill-card__conf-unit">%</span>
                            </div>
                          </header>

                          <div className="skill-card__sub">
                            <span className="skill-card__chip">
                              <span className="skill-card__chip-label">熟练度</span>
                              <span>{proficiencyLabel(skill.proficiency)}</span>
                            </span>
                            <span className="skill-card__chip">
                              <span className="skill-card__chip-label">证据强度</span>
                              <span>{evidenceLabel(skill.evidence_strength)}</span>
                            </span>
                          </div>

                          <div className="skill-bar" aria-label={`置信度 ${confidence}%`}>
                            <div className="skill-bar__track">
                              <div
                                className={`skill-bar__fill ${mapped ? 'is-mapped' : 'is-unmapped'}`}
                                style={{ width: `${confidence}%` }}
                              />
                            </div>
                            <span className="skill-bar__ruler" aria-hidden>
                              <i />
                              <i />
                              <i />
                              <i />
                              <i />
                            </span>
                          </div>

                          {skill.evidence_quote && (
                            <blockquote className="skill-quote">
                              <span className="skill-quote__mark">「</span>
                              <p>{skill.evidence_quote}</p>
                              <span className="skill-quote__mark">」</span>
                            </blockquote>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <div className="skill-board__empty">
                  <span>后端没有返回可确认技能</span>
                  <em>可在右侧手动补充后确认画像。</em>
                </div>
              )}
            </section>

            {/* ── 右：画像摘要 + 人工修订 + 确认 ──────────────── */}
            <aside className="profile-board archive-panel glass rounded-2xl overflow-hidden flex flex-col">
              <FrameCorners />
              <div className="profile-board__bg" />

              <header className="profile-board__head">
                <div>
                  <div className="profile-board__kicker">
                    <span>Profile digest · 画像摘要</span>
                  </div>
                  <h3 className="profile-board__title">候选人画像快照</h3>
                  <p className="profile-board__summary">{summary}</p>
                </div>
                {resumeContentUrl && (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost profile-board__view"
                    onClick={() => window.open(resumeContentUrl, '_blank', 'noopener,noreferrer')}
                  >
                    <FolderOpenOutlined /> 查看上传原件
                  </button>
                )}
              </header>

              <dl className="profile-meta">
                <div className="profile-meta__item">
                  <dt>EDUCATION</dt>
                  <dd>{educationLabel(resumeProfile.highest_education_level)}</dd>
                </div>
                <div className="profile-meta__item">
                  <dt>EXPERIENCE</dt>
                  <dd>{formatMonths(resumeProfile.total_experience_months)}</dd>
                </div>
                <div className="profile-meta__item">
                  <dt>METHOD</dt>
                  <dd>{resumeProfile.text_extraction_method.toUpperCase()}</dd>
                </div>
                <div className="profile-meta__item">
                  <dt>VERSION</dt>
                  <dd>V{resumeProfile.version_no}</dd>
                </div>
              </dl>

              {(educations.length > 0 || experiences.length > 0 || projects.length > 0) && (
                <section className="profile-evidence">
                  <header className="profile-evidence__head">
                    <span className="profile-evidence__tag">
                      Evidence preview
                    </span>
                    <span className="profile-evidence__count">
                      {educations.length + experiences.length + projects.length} ENTRIES
                    </span>
                  </header>
                  <ul className="profile-evidence__list">
                    {[
                      ...educations.slice(0, 1).map((item: Record<string, any>) => ({
                        label: '教育经历',
                        short: 'EDU',
                        title: itemText(item, ['school_name', 'major']),
                        meta: dateRange(item),
                      })),
                      ...experiences.slice(0, 1).map((item: Record<string, any>) => ({
                        label: '工作经历',
                        short: 'EXP',
                        title: itemText(item, ['company_name', 'job_title']),
                        meta: dateRange(item),
                      })),
                      ...projects.slice(0, 1).map((item: Record<string, any>) => ({
                        label: '项目证据',
                        short: 'PRJ',
                        title: itemText(item, ['project_name', 'role']),
                        meta: dateRange(item),
                      })),
                    ].map((item) => (
                      <li key={`${item.label}-${item.title}`}>
                        <button
                          type="button"
                          className="profile-evidence__card"
                          onClick={() => resumeContentUrl && window.open(resumeContentUrl, '_blank', 'noopener,noreferrer')}
                          disabled={!resumeContentUrl}
                        >
                          <span className="profile-evidence__badge">{item.short}</span>
                          <div className="profile-evidence__body">
                            <h4>{item.label} · {item.title || '未命名条目'}</h4>
                            <span>{item.meta}</span>
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {workflowError && (
                <div className="profile-error">
                  <WarningOutlined /> {workflowError}
                </div>
              )}

              <section className="profile-revision">
                <label className="profile-revision__label">
                  <span>Human revision</span>
                  <em>人工修订技能</em>
                </label>
                <textarea
                  className="profile-revision__input"
                  rows={3}
                  placeholder="用英文逗号分隔补充或替换技能名，例如：FastAPI, Pandas, PyTorch, Distributed Training"
                  value={editedSkills}
                  onChange={(event) => setEditedSkills(event.target.value)}
                />
                <div className="profile-revision__actions">
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost flex-1"
                    onClick={() => void saveProfileRevision()}
                    disabled={revisionSaving || !editedSkills.trim()}
                  >
                    {revisionSaving ? <LoadingOutlined /> : <ReloadOutlined />}
                    保存修订草稿
                  </button>
                </div>
              </section>

              <button
                type="button"
                className="btn profile-confirm"
                onClick={handleConfirmAndRecommend}
                disabled={recommendationLoading}
              >
                <span className="profile-confirm__icon">
                  {recommendationLoading ? <LoadingOutlined /> : <CheckCircleOutlined />}
                </span>
                <span className="profile-confirm__body">
                  <strong>确认画像</strong>
                  <em>生成岗位推荐</em>
                </span>
                <ArrowRightOutlined />
              </button>
            </aside>
          </div>
        )}

        {step === 2 && recommendations && (
          <div className="applicant-match-panel animate-fade-up">
            <div className="applicant-tabs flex gap-1 mb-5">
              {(['radar', 'skills', 'graph', 'path'] as const).map((tab) => (
                <button
                  key={tab}
                  className={`btn btn-sm ${activeTab === tab ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === 'radar' ? (
                    <>
                      <RadarChartOutlined />
                      能力雷达
                    </>
                  ) : tab === 'skills' ? (
                    <>
                      <SwapOutlined />
                      技能对比
                    </>
                  ) : tab === 'graph' ? (
                    <>
                      <FundProjectionScreenOutlined />
                      岗位图谱
                    </>
                  ) : (
                    <>
                      <CompassOutlined />
                      成长路径
                    </>
                  )}
                </button>
              ))}
            </div>

            <FadeContent duration={700} delay={0.1} threshold={0.05}>
            <div className="applicant-match-grid grid grid-cols-2 gap-6">
              <div className="archive-panel glass rounded-2xl p-6">
                <FrameCorners />
                {activeTab === 'radar' && (
                  <>
                    <div className="flex items-start justify-between gap-3 mb-1">
                      <div>
                        <div className="font-outfit font-bold text-[15px] text-[var(--text)]">能力雷达图</div>
                        <div className="text-xs text-[var(--text-dim)] mt-0.5">
                          {selectedResult ? `与 ${selectedResult.job_role.canonical_name} 对比` : '等待选择岗位'}
                        </div>
                      </div>
                      {selectedResult && (
                        <div className="text-right flex-shrink-0">
                          <div className="font-jetbrains text-[9px] text-[#e4b592] tracking-[0.14em]">综合得分</div>
                          <div className="font-jetbrains text-[24px] font-bold text-[var(--text)] leading-none mt-1">
                            {toPercent(selectedResult.total_score)}
                            <span className="text-[11px] text-[var(--text-dim)] ml-0.5">%</span>
                          </div>
                        </div>
                      )}
                    </div>
                    <ResponsiveContainer width="100%" height={250}>
                      <RadarChart data={selectedRadarData}>
                        <PolarGrid stroke="rgba(255,243,234,0.18)" />
                        <PolarAngleAxis dataKey="axis" tick={{ fill: '#a49b92', fontSize: 11, fontFamily: 'IBM Plex Mono' }} />
                        <Radar dataKey="score" stroke="#e4b592" fill="#e4b592" fillOpacity={0.12} strokeWidth={2} dot={{ fill: '#e4b592', r: 3 }} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </>
                )}

                {activeTab === 'skills' && (
                  <div className="flex flex-col gap-3">
                    {detailLoading && (
                      <div className="text-[13px] text-[var(--text-dim)]">
                        <LoadingOutlined /> 正在读取岗位差距
                      </div>
                    )}
                    {detailError && (
                      <div className="border border-[rgba(238,18,18,0.45)] bg-[rgba(238,18,18,0.06)] px-3 py-2 text-[12px] text-[#ee1212]">
                        <WarningOutlined /> {detailError}
                      </div>
                    )}
                    {!detailLoading && selectedMatchDetail && (
                      matchedCapabilities.length === 0 && missingCapabilities.length === 0 ? (
                        <div className="border border-[var(--border)] px-4 py-6 text-center">
                          <div className="text-[13px] text-[var(--text)]">该岗位暂无标准化能力对比数据</div>
                          <div className="text-[12px] text-[var(--text-dim)] mt-1.5 leading-5">
                            可能是简历技能较少，或该岗位定义尚未映射能力项；可切换右侧其他岗位查看。
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="font-outfit font-bold text-[15px] text-[#dad0c8]">
                            <CheckCircleOutlined /> 已匹配 ({matchedCapabilities.length})
                          </div>
                          <div className="flex flex-wrap gap-1.5 mb-3">
                            {matchedCapabilities.map((item) => (
                              <span key={item.capability_id} className="tag tag-green">
                                {item.canonical_name}
                              </span>
                            ))}
                          </div>
                          <div className="font-outfit font-bold text-[15px] text-[#ee1212]">
                            <CloseCircleOutlined /> 缺失必备 ({missingRequired.length})
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {missingRequired.map((item) => (
                              <span key={item.capability_id} className="tag tag-red">
                                {item.canonical_name} · {item.skill_type}
                              </span>
                            ))}
                          </div>
                          {missingBonus.length > 0 && (
                            <>
                              <div className="font-outfit font-bold text-[15px] text-[#e4b592] mt-2">
                                <SwapOutlined /> 加分缺口 ({missingBonus.length})
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {missingBonus.map((item) => (
                                  <span key={item.capability_id} className="tag tag-purple">
                                    {item.canonical_name}
                                  </span>
                                ))}
                              </div>
                            </>
                          )}
                        </>
                      )
                    )}
                  </div>
                )}

                {activeTab === 'graph' && (
                  <div className="applicant-role-graph">
                    <div className="applicant-role-graph__head">
                      <div>
                        <div className="font-outfit font-bold text-[15px] text-[var(--text)]">岗位知识图谱</div>
                        <div className="text-xs text-[var(--text-dim)] mt-1">
                          {selectedResult ? `当前锚定：${selectedResult.job_role.canonical_name}` : '等待选择匹配岗位'}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => navigate(selectedRoleGraphPath)}
                        disabled={!selectedResult}
                      >
                        打开星图
                        <ArrowRightOutlined />
                      </button>
                    </div>

                    <div className="applicant-role-graph__canvas graph-canvas-frame graph-canvas-frame--archive relative overflow-hidden">
                      <FrameCorners />
                      {jobGraphLoading && (
                        <div className="applicant-role-graph__state">
                          <div className="loading-reticle" />
                          <strong>正在读取岗位图谱</strong>
                          <span>加载本地 JD 星图并匹配当前推荐岗位</span>
                        </div>
                      )}

                      {!jobGraphLoading && jobGraphError && (
                        <div className="applicant-role-graph__state applicant-role-graph__state--error">
                          <WarningOutlined />
                          <strong>岗位图谱暂不可用</strong>
                          <span>{jobGraphError}</span>
                          <button type="button" className="btn btn-sm btn-ghost mt-1" onClick={reloadJobGraph}>
                            <ReloadOutlined />
                            重新加载
                          </button>
                        </div>
                      )}

                      {!jobGraphLoading && !jobGraphError && !selectedJobGraphData && (
                        <div className="applicant-role-graph__state">
                          <FundProjectionScreenOutlined />
                          <strong>未匹配到图谱节点</strong>
                          <span>当前推荐岗位未能和 JD 星图中的岗位节点对齐，可打开完整星图手动搜索。</span>
                        </div>
                      )}

                      {!jobGraphLoading && !jobGraphError && selectedJobGraphData && (
                        <>
                          <GraphScene3D
                            data={selectedJobGraphData}
                            selectedStar={selectedGraphStar}
                            selectedPlanet={selectedGraphPlanet}
                            onStarClick={(star) => {
                              setSelectedGraphStar(star)
                              setSelectedGraphPlanet(null)
                            }}
                            onPlanetClick={(planet) => {
                              setSelectedGraphPlanet(planet)
                              setSelectedGraphStar(null)
                            }}
                            showJobLabels
                            showSkillLabels
                            filterTypes={['core', 'foundation', 'frontier']}
                          />
                          <div className="applicant-role-graph__readout archive-panel glass">
                            <span>FOCUS</span>
                            <strong>{graphFocusLabel}</strong>
                          </div>
                        </>
                      )}
                    </div>

                    <div className="applicant-role-graph__summary">
                      <div>
                        <span>图谱技能</span>
                        <strong>{selectedJobGraphData?.planets.length ?? 0}</strong>
                      </div>
                      <div>
                        <span>简历已覆盖</span>
                        <strong>{matchedCapabilities.length}</strong>
                      </div>
                      <div>
                        <span>必备缺口</span>
                        <strong>{missingRequired.length}</strong>
                      </div>
                    </div>
                  </div>
                )}

                {activeTab === 'path' && (
                  <div>
                    <div className="font-outfit font-bold text-[15px] text-[var(--text)] mb-3.5">成长路径</div>
                    {currentGrowthPath ? (
                      <div className="flex flex-col gap-3">
                        <p className="text-[13px] leading-6 text-[var(--text-dim)]">{currentGrowthPath.plan.summary}</p>
                        {currentGrowthPath.plan.stages.slice(0, 3).map((stage) => (
                          <div key={stage.stage_no} className="border border-[var(--border)] px-3.5 py-3">
                            <div className="font-jetbrains text-[9px] text-[#e4b592]">STAGE {stage.stage_no} / {stage.estimated_weeks}W</div>
                            <div className="text-[13px] text-[var(--text)] mt-1">{stage.title}</div>
                            <div className="text-[12px] text-[var(--text-dim)] mt-1">{stage.objective}</div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="border border-[var(--border)] px-4 py-4">
                        <div className="text-[13px] text-[var(--text)] mb-2">当前岗位成长路径尚未生成。</div>
                        {growthError && <div className="text-[12px] text-[#ee1212] mb-3"><WarningOutlined /> {growthError}</div>}
                        <button className="btn btn-sm btn-primary" onClick={handleCreateGrowthPath} disabled={growthLoading || !selectedResult}>
                          {growthLoading ? <LoadingOutlined /> : <CompassOutlined />}
                          生成成长路径
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="applicant-job-list-panel">
                <div className="font-outfit font-bold text-[15px] text-[var(--text)] mb-3.5">
                  <TrophyOutlined /> 匹配岗位排行
                </div>
                <div className="flex flex-col gap-3">
                  {visibleJobs.map((job, i) => {
                    const active = job.job_role_id === selectedJobRoleId
                    const color = matchLevelColor(job.match_level)
                    return (
                      <button
                        key={job.job_role_id}
                        className="archive-row glass rounded-xl p-3.5 px-4 flex items-center gap-3 animate-fade-up text-left"
                        style={{
                          animationDelay: `${Math.min(i, 8) * 60}ms`,
                          borderLeft: active ? `3px solid ${color}` : '3px solid transparent',
                          cursor: 'pointer',
                        }}
                        onClick={() => {
                          setSelectedJobRoleId(job.job_role_id)
                          setActiveTab((tab) => (tab === 'path' ? 'radar' : tab))
                        }}
                      >
                        <Ring v={job.total_score} size={56} color={color} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="font-jetbrains text-[10px] text-[var(--text-dim)] flex-shrink-0">
                              #{String(job.rank ?? i + 1).padStart(2, '0')}
                            </span>
                            <span className="font-outfit font-bold text-sm text-[var(--text)] truncate">
                              {job.job_role.canonical_name}
                            </span>
                            <span
                              className="font-jetbrains text-[9px] px-1.5 py-0.5 flex-shrink-0"
                              style={{
                                background: `${color}18`,
                                border: `1px solid ${color}40`,
                                color,
                              }}
                            >
                              {matchLevelLabel(job.match_level)}
                            </span>
                          </div>
                          <div className="prog-track">
                            <div className="prog-fill" style={{ width: `${clampPercent(job.total_score)}%`, background: color }} />
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
                {jobItems.length > TOP_JOB_COUNT && (
                  <button className="btn btn-sm btn-ghost w-full mt-3" onClick={() => setShowAllJobs((v) => !v)}>
                    {showAllJobs ? '收起，仅显示前列岗位' : `展开全部 ${jobItems.length} 个岗位`}
                  </button>
                )}
                <button className="btn btn-md btn-primary w-full mt-5" onClick={handleCreateGrowthPath} disabled={growthLoading || !selectedResult}>
                  {growthLoading ? <LoadingOutlined /> : <CompassOutlined />}
                  生成成长路径 <ArrowRightOutlined />
                </button>
              </div>
            </div>
            </FadeContent>
          </div>
        )}

        {step === 3 && (
          <div className="applicant-gap-grid animate-fade-up">
            {currentGrowthPath ? (
              <>
                {/* ── 头部目标概览卡片 ──────────────────────────────── */}
                <div className="growth-hero archive-panel glass rounded-2xl overflow-hidden">
                  <FrameCorners />
                  <div className="growth-hero__bg" />
                  <div className="growth-hero__inner">
                    <div className="growth-hero__kicker">
                      <CheckCircleOutlined />
                      <span>Target profile · 目标岗位画像</span>
                    </div>
                    <h2 className="growth-hero__title">
                      {currentGrowthPath.plan.target_role.canonical_name}
                    </h2>
                    <p className="growth-hero__summary">{currentGrowthPath.plan.summary}</p>

                    <dl className="growth-hero__meta">
                      <div>
                        <dt>TOTAL</dt>
                        <dd>
                          <span className="growth-hero__num">
                            <CountUp to={currentGrowthPath.plan.total_estimated_weeks} duration={1.3} />
                          </span>
                          <em>周</em>
                        </dd>
                      </div>
                      <div>
                        <dt>GAPS</dt>
                        <dd>
                          <span className="growth-hero__num">{missingRequired.length}</span>
                          <em>必备</em>
                        </dd>
                      </div>
                      <div>
                        <dt>STAGES</dt>
                        <dd>
                          <span className="growth-hero__num">{currentGrowthPath.plan.stages.length}</span>
                          <em>阶段</em>
                        </dd>
                      </div>
                      <div>
                        <dt>CAPS</dt>
                        <dd>
                          <span className="growth-hero__num">
                            {currentGrowthPath.plan.stages.reduce((acc, s) => acc + s.capabilities.length, 0)}
                          </span>
                          <em>能力项</em>
                        </dd>
                      </div>
                    </dl>

                    {missingRequired.length > 0 && (
                      <div className="growth-hero__gaps">
                        <div className="growth-hero__gaps-title">
                          <CloseCircleOutlined />
                          <span>必备能力缺口（{missingRequired.length}）</span>
                        </div>
                        <div className="growth-hero__gaps-tags">
                          {missingRequired.map((item) => (
                            <span key={item.capability_id} className="tag tag-red">
                              {item.canonical_name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* ── 阶段时间线 ────────────────────────────────────── */}
                <div className="growth-timeline archive-panel glass rounded-2xl">
                  <FrameCorners />
                  <div className="growth-timeline__head">
                    <div className="growth-timeline__title">
                      <CompassOutlined />
                      <span>阶段性成长路径</span>
                    </div>
                    <div className="growth-timeline__progress">
                      <span>Mission deck · 阶段共 {currentGrowthPath.plan.stages.length} 节</span>
                    </div>
                  </div>

                  <ol className="growth-timeline__list">
                    {currentGrowthPath.plan.stages.map((stage, index) => (
                      <li
                        key={stage.stage_no}
                        className="growth-stage"
                        style={{ animationDelay: `${Math.min(index, 10) * 80}ms` }}
                      >
                        <div className="growth-stage__rail" aria-hidden>
                          <span className="growth-stage__dot" />
                          {index < currentGrowthPath.plan.stages.length - 1 && (
                            <span className="growth-stage__line" />
                          )}
                        </div>
                        <div className="growth-stage__card">
                          <header className="growth-stage__head">
                            <div className="growth-stage__badge">
                              <span className="growth-stage__no">{String(stage.stage_no).padStart(2, '0')}</span>
                              <span className="growth-stage__weeks">{stage.estimated_weeks} W</span>
                            </div>
                            <div className="growth-stage__meta">
                              <h4>{stage.title}</h4>
                              <span>{stage.capabilities.length} CAPS</span>
                            </div>
                          </header>

                          <p className="growth-stage__objective">{stage.objective}</p>

                          <ul className="growth-stage__actions">
                            {stage.actions.slice(0, 3).map((action, actionIndex) => (
                              <li key={action}>
                                <span className="growth-stage__order">{actionIndex + 1}</span>
                                <p>{action}</p>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </li>
                    ))}
                  </ol>

                  {/* ── 最终实战项目 ─────────────────────────────────── */}
                  <div className="growth-final">
                    <div className="growth-final__tag">Final project · 实战收尾</div>
                    <p>{currentGrowthPath.plan.final_project}</p>
                  </div>

                  <div className="applicant-final-actions">
                    <button className="btn btn-sm btn-primary flex-1" onClick={() => setStep(2)}>
                      返回岗位推荐
                    </button>
                    <button className="btn btn-sm btn-ghost flex-1" onClick={() => navigate(selectedRoleGraphPath)}>
                      查看该岗位图谱
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div className="archive-panel glass rounded-2xl p-6 col-span-2">
                <FrameCorners />
                <div className="font-outfit font-bold text-[18px] text-[var(--text)] mb-2">成长路径尚未生成</div>
                <p className="text-[13px] text-[var(--text-dim)] mb-4">
                  请先在岗位匹配页选择岗位，再调用后端成长路径接口生成真实路径。
                </p>
                {growthError && <div className="text-[12px] text-[#ee1212] mb-4"><WarningOutlined /> {growthError}</div>}
                <button className="btn btn-md btn-primary" onClick={handleCreateGrowthPath} disabled={growthLoading || !selectedResult}>
                  {growthLoading ? <LoadingOutlined /> : <CompassOutlined />}
                  生成成长路径
                </button>
              </div>
            )}
          </div>
        )}

        {step > 0 && (
          <div className="mt-7">
            <button className="btn btn-sm btn-ghost" onClick={() => setStep((s) => Math.max(0, s - 1) as Step)}>
              <ArrowLeftOutlined /> 返回上一步
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
