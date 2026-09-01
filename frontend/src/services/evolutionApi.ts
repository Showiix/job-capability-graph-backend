import request from '../utils/request'

export interface EvolutionItem {
  id: string
  job_name: string
  skill: string
  change_type: string
  effect_size: number
  confidence: '高' | '中' | '低'
  action: string
  controls: Record<string, any>
  evidence: {
    jd_count?: number
    companies?: string[]
    sources?: Record<string, number>
    samples?: Array<{ company: string; source: string; issue_date: string; city: string; snippet: string }>
  }
  update_summary?: string
  trend_description?: string
}

export interface EvolutionPage {
  items: EvolutionItem[]
  total: number
  page: number
  page_size: number
  statistics: Record<string, any>
}

export function listEvolution(params: {
  query?: string
  change_type?: string
  confidence?: string
  page: number
  page_size: number
}) {
  return request.get<EvolutionPage>('/api/v1/capability-evolution', { params })
}
