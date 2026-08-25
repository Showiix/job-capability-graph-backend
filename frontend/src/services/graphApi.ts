import axios from 'axios'
import type { GraphData } from '../types/graph'
import { API_BASE_URL } from './apiBase'

// API 响应格式
interface ApiResponse<T> {
  code: number
  data: T
  message: string
}

// 知识图谱 API 响应
interface GraphApiNode {
  id: string
  label: string
  type: 'job' | 'skill'
  level?: '基础' | '核心' | '前沿'
  is_new?: boolean
}

interface GraphApiEdge {
  source: string
  target: string
  weight: number
}

interface GraphApiResponse {
  nodes: GraphApiNode[]
  edges: GraphApiEdge[]
}

interface JDGraphSampleJob {
  jobName: string
  companyName: string
  salary: string
  city: string
  education: string
  workYear: string
  source: string
  url: string
}

interface JDGraphStar {
  id: string
  name?: string
  label?: string
  domain?: string
  color?: string
  position?: [number, number, number]
  size?: number
  jobCount?: number
  sources?: number
  requiredSkills?: string[]
  bonusSkills?: string[]
  isEmerging?: boolean
  sourceCounts?: Record<string, number>
  sampleJobs?: JDGraphSampleJob[]
}

interface JDGraphPlanet {
  id: string
  name?: string
  label?: string
  type?: 'core' | 'foundation' | 'frontier'
  starId: string
  isRequired?: boolean
  distance?: number
  orbitRadius?: number
  orbitTilt?: number
  orbitPhase?: number
  speed?: number
  orbitSpeed?: number
  size?: number
  confidence?: number
  color?: string
  relatedJobs?: number
  frequency?: number
  isEmerging?: boolean
}

interface JDGraphResponse {
  stars: JDGraphStar[]
  planets: JDGraphPlanet[]
  metadata?: GraphData['metadata']
}

// 技能数据
interface SkillData {
  name: string
  level: '基础' | '核心' | '前沿'
  proficiency?: number
  weight?: number
}

// 简历解析响应
interface ResumeParseResponse {
  name: string
  skills: SkillData[]
}

// 岗位解析响应
interface JDParseResponse {
  job_title: string
  job_id: string
  required_skills: SkillData[]
}

// 匹配响应
interface MatchResponse {
  match_score: number
  matched_skills: Array<{ name: string; proficiency: number }>
  gap_skills: Array<{
    name: string
    level: string
    required_proficiency: number
    user_proficiency: number
  }>
}

// 技能趋势响应
interface SkillTrendResponse {
  skill_name: string
  confidence_score: number
  trend: '上升' | '稳定' | '下降'
  evidence_count: number
  timeline: Array<{ date: string; jd_count: number }>
  warning: string | null
}

/**
 * 获取知识图谱数据
 */
export async function fetchGraphData(params?: {
  category?: string
  level?: string
}): Promise<GraphData> {
  try {
    const jdResponse = await axios.get<ApiResponse<JDGraphResponse>>(
      `${API_BASE_URL}/api/v1/jd-graph`,
      { params }
    )

    if (jdResponse.data.code === 200) {
      return convertJdGraphData(jdResponse.data.data)
    }

    throw new Error(jdResponse.data.message || '加载 JD 图谱失败')
  } catch (error) {
    console.error('[API Error] fetchGraphData(jd-graph):', error)

    try {
      const legacyResponse = await axios.get<ApiResponse<GraphApiResponse>>(
        `${API_BASE_URL}/api/v1/graph`,
        { params }
      )

      if (legacyResponse.data.code !== 200) {
        throw new Error(legacyResponse.data.message)
      }

      return convertLegacyGraphData(legacyResponse.data.data)
    } catch (legacyError) {
      console.error('[API Error] fetchGraphData(legacy):', legacyError)

      try {
        const localResponse = await axios.get<JDGraphResponse>('/jd_graph_data.json')
        return convertJdGraphData(localResponse.data)
      } catch (localError) {
        console.error('[API Error] fetchGraphData(local):', localError)
        throw localError
      }
    }
  }
}

export async function fetchGraphStats() {
  const response = await axios.get<{ data: Record<string, any> }>(`${API_BASE_URL}/api/v1/jd-graph/stats`)
  return response.data.data
}

export async function fetchGraphTrends(months = 7) {
  const response = await axios.get<{ data: { timeline: any[]; hot_skills: any[]; coverage: Record<string, number> } }>(`${API_BASE_URL}/api/v1/jd-graph/trends`, { params: { months } })
  return response.data.data
}

/**
 * 简历解析
 */
// Legacy parse/match helpers are retained for compatibility; live pages use resumeWorkflowApi.
export async function parseResume(file: File): Promise<ResumeParseResponse> {
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await axios.post<ApiResponse<ResumeParseResponse>>(
      `${API_BASE_URL}/api/v1/resume/parse`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )

    if (response.data.code !== 200) {
      throw new Error(response.data.message)
    }

    return response.data.data
  } catch (error) {
    console.error('[API Error] parseResume:', error)
    throw error
  }
}

/**
 * 岗位描述解析
 */
export async function parseJD(text: string): Promise<JDParseResponse> {
  try {
    const response = await axios.post<ApiResponse<JDParseResponse>>(
      `${API_BASE_URL}/api/v1/jd/parse`,
      { text }
    )

    if (response.data.code !== 200) {
      throw new Error(response.data.message)
    }

    return response.data.data
  } catch (error) {
    console.error('[API Error] parseJD:', error)
    throw error
  }
}

/**
 * 人岗匹配
 */
export async function matchJob(
  userSkills: SkillData[],
  jobId: string
): Promise<MatchResponse> {
  try {
    const response = await axios.post<ApiResponse<MatchResponse>>(
      `${API_BASE_URL}/api/v1/match`,
      {
        user_skills: userSkills,
        job_id: jobId,
      }
    )

    if (response.data.code !== 200) {
      throw new Error(response.data.message)
    }

    return response.data.data
  } catch (error) {
    console.error('[API Error] matchJob:', error)
    throw error
  }
}

/**
 * 获取技能趋势
 */
export async function fetchSkillTrend(
  skillName: string
): Promise<SkillTrendResponse> {
  try {
    const response = await axios.get<ApiResponse<SkillTrendResponse>>(
      `${API_BASE_URL}/api/v1/skill/trend`,
      {
        params: { skill_name: skillName },
      }
    )

    if (response.data.code !== 200) {
      throw new Error(response.data.message)
    }

    return response.data.data
  } catch (error) {
    console.error('[API Error] fetchSkillTrend:', error)
    throw error
  }
}

function convertJdGraphData(apiData: JDGraphResponse): GraphData {
  const stars = (apiData.stars || []).map((star, index) => {
    const label = star.label || star.name || `岗位 ${index + 1}`
    return {
      id: star.id,
      label,
      name: star.name || label,
      domain: star.domain || '岗位类别',
      color: star.color || getJobColor(index, star.isEmerging),
      position: normalizePosition(star.position, index),
      size: normalizeStarSize(star.size),
      requiredSkills: star.requiredSkills || [],
      bonusSkills: star.bonusSkills || [],
      sources: star.sources ?? star.jobCount ?? 0,
      jobCount: star.jobCount ?? star.sources ?? 0,
      isEmerging: star.isEmerging,
      sourceCounts: star.sourceCounts,
      sampleJobs: star.sampleJobs,
    }
  })

  const starsById = new Map(stars.map((star) => [star.id, star]))
  const planets = (apiData.planets || [])
    .map((planet, index) => {
      const label = planet.label || planet.name || `技能 ${index + 1}`
      return {
        id: planet.id,
        starId: planet.starId,
        label,
        type: planet.type || 'foundation',
        isRequired: Boolean(planet.isRequired),
        orbitRadius: planet.orbitRadius ?? planet.distance ?? 4,
        orbitTilt: planet.orbitTilt ?? Math.PI / 10,
        orbitPhase: planet.orbitPhase ?? (index % 12) * 0.45,
        orbitSpeed: planet.orbitSpeed ?? planet.speed ?? 0.14,
        size: normalizePlanetSize(planet.size),
        confidence: Math.round(planet.confidence ?? (planet.frequency ? Math.min(98, Math.max(52, planet.frequency)) : 68)),
        color: planet.color || getSkillColor(planet.type || 'foundation'),
      }
    })
    .filter((planet) => Boolean(starsById.get(planet.starId)))

  return {
    stars,
    planets,
    metadata: apiData.metadata,
  }
}

function convertLegacyGraphData(apiData: GraphApiResponse): GraphData {
  const { nodes, edges } = apiData

  // 分离岗位节点和技能节点
  const jobNodes = nodes.filter((n) => n.type === 'job')
  const skillNodes = nodes.filter((n) => n.type === 'skill')

  // 构建岗位（恒星）数据
  const stars = jobNodes.map((job, index) => {
    // 找到该岗位的所有技能边
    const jobEdges = edges.filter((e) => e.source === job.id)

    // 按权重分类必备技能和加分技能
    const requiredSkills: string[] = []
    const bonusSkills: string[] = []

    jobEdges.forEach((edge) => {
      const skill = skillNodes.find((s) => s.id === edge.target)
      if (skill) {
        if (edge.weight >= 0.7) {
          requiredSkills.push(skill.label)
        } else {
          bonusSkills.push(skill.label)
        }
      }
    })

    // 生成星图空间位置（螺旋分布）
    const angle = (index / jobNodes.length) * Math.PI * 2
    const radius = 5 + Math.random() * 3

    return {
      id: job.id,
      label: job.label,
      domain: job.is_new ? '新兴岗位' : '传统岗位',
      color: getJobColor(index, job.is_new),
      position: [
        Math.cos(angle) * radius,
        (Math.random() - 0.5) * 4,
        Math.sin(angle) * radius,
      ] as [number, number, number],
      size: 1.0 + (requiredSkills.length / 10) * 0.3,
      requiredSkills,
      bonusSkills,
      sources: jobEdges.length,
    }
  })

  // 构建行星（技能）数据
  const planets = stars.flatMap((star) => {
    const allSkills = [...star.requiredSkills, ...star.bonusSkills]

    return allSkills.map((skillName, index) => {
      const isRequired = star.requiredSkills.includes(skillName)
      const skillNode = skillNodes.find((s) => s.label === skillName)
      const level = skillNode?.level || '核心'

      return {
        id: `${star.id}_${skillName}`,
        starId: star.id,
        label: skillName,
        type: mapLevel(level),
        isRequired,
        orbitRadius: isRequired ? 2 + index * 0.6 : 4 + (index - star.requiredSkills.length) * 0.7,
        orbitTilt: Math.PI / (isRequired ? 8 : 10),
        orbitPhase: (index / allSkills.length) * Math.PI * 2,
        orbitSpeed: isRequired ? 0.3 - index * 0.05 : 0.15 - index * 0.02,
        size: isRequired ? 0.25 : 0.2,
        confidence: 70 + Math.floor(Math.random() * 28),
        color: getSkillColor(level),
      }
    })
  })

  return { stars, planets }
}

function normalizePosition(
  position: [number, number, number] | undefined,
  index: number
): [number, number, number] {
  if (position && position.length === 3) {
    return position
  }

  const angle = (index / 24) * Math.PI * 2
  const radius = 6 + (index % 7) * 1.35
  return [
    Math.cos(angle) * radius,
    ((index * 3) % 7) - 3,
    Math.sin(angle) * radius,
  ]
}

function normalizeStarSize(size?: number): number {
  if (!size || Number.isNaN(size)) {
    return 1
  }

  if (size > 5) {
    return Math.max(0.75, Math.min(size / 16, 1.8))
  }

  return Math.max(0.72, Math.min(size, 1.8))
}

function normalizePlanetSize(size?: number): number {
  if (!size || Number.isNaN(size)) {
    return 0.2
  }

  if (size > 1) {
    return Math.max(0.16, Math.min(size / 16, 0.28))
  }

  return Math.max(0.16, Math.min(size, 0.28))
}

/**
 * 获取岗位颜色
 */
function getJobColor(index: number, isNew?: boolean): string {
  if (isNew) {
    return '#ee1212'
  }

  const colors = ['#fff3ea', '#e4b592', '#dad0c8', '#b9aea4', '#ee1212']
  return colors[index % colors.length]
}

/**
 * 获取技能颜色
 */
function getSkillColor(level: string): string {
  const colorMap: Record<string, string> = {
    基础: '#dad0c8',
    核心: '#ee1212',
    前沿: '#e4b592',
  }
  return colorMap[level] || '#ee1212'
}

/**
 * 映射技能等级
 */
function mapLevel(level: string): 'core' | 'foundation' | 'frontier' {
  const levelMap: Record<string, 'core' | 'foundation' | 'frontier'> = {
    基础: 'foundation',
    核心: 'core',
    前沿: 'frontier',
  }
  return levelMap[level] || 'core'
}

export default {
  fetchGraphData,
  fetchGraphStats,
}
