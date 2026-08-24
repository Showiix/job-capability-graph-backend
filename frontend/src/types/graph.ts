// 星图数据类型定义
export interface Star {
  id: string
  label: string
  name?: string
  domain: string
  color: string
  position: [number, number, number]
  size: number
  jobCount?: number
  requiredSkills: string[]
  bonusSkills: string[]
  sources: number
  isEmerging?: boolean
  sourceCounts?: Record<string, number>
  sampleJobs?: Array<{
    jobName: string
    companyName: string
    salary: string
    city: string
    education: string
    workYear: string
    source: string
    url: string
  }>
}

export interface Planet {
  id: string
  starId: string
  label: string
  type: 'core' | 'foundation' | 'frontier'
  isRequired: boolean
  orbitRadius: number
  orbitTilt: number
  orbitPhase: number
  orbitSpeed: number
  size: number
  confidence: number
  color: string
}

export interface GraphData {
  stars: Star[]
  planets: Planet[]
  metadata?: {
    total_jobs?: number
    total_categories?: number
    total_skills?: number
    total_planets?: number
    total_files?: number
    source_counts?: Record<string, number>
    featured_star_ids?: string[]
    featured_categories?: string[]
    generated_at?: string
  }
}
