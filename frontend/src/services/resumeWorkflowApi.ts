import request from '../utils/request'
import type { AxiosProgressEvent } from 'axios'

export interface ResumeCreateResponse {
  resource_id: string
  run_id: string
  status: 'processing'
  poll_url: string
}

export interface ResumeProcessingResult {
  result_url: string
  resume_id: string
  profile_id: string
  profile_version: number
  mapped_skill_count: number
  unmapped_skill_count: number
  validation_warning_count: number
}

export interface ProcessingRunResponse {
  id: string
  run_type: string
  subject_type: string
  subject_id: string
  retry_of_run_id: string | null
  status:
    | 'pending'
    | 'enqueue_failed'
    | 'running'
    | 'waiting_review'
    | 'cancel_requested'
    | 'completed'
    | 'failed'
    | 'cancelled'
  current_stage: string | null
  pipeline_version: string
  celery_task_id: string | null
  total_count: number
  processed_count: number
  success_count: number
  failed_count: number
  progress_percent: number
  cancel_requested: boolean
  attempt_count: number
  max_attempts: number
  error_code: string | null
  error_message: string | null
  enqueued_at: string | null
  started_at: string | null
  heartbeat_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface ResumeSkillRecord {
  id: string
  raw_name: string
  normalized_name: string
  capability_id: string | null
  capability_name: string | null
  proficiency: 'beginner' | 'intermediate' | 'advanced' | null
  explicit_experience_months: number | null
  evidence_strength: 'mention' | 'project' | 'work'
  evidence_quote: string | null
  evidence_start: number | null
  evidence_end: number | null
  mapping_method: 'canonical_exact' | 'alias_exact' | 'manual' | 'unmapped'
  mapping_status: 'mapped' | 'unmapped'
  source: 'llm' | 'manual'
  confidence: number
  user_confirmed: boolean
}

export interface ResumeProfileDetail {
  id: string
  resume_id: string
  version_no: number
  base_profile_version: number | null
  profile_source: 'extracted' | 'manual_revision'
  status: 'candidate' | 'draft' | 'confirmed' | 'superseded'
  extraction_version: string
  highest_education_level: string | null
  total_experience_months: number | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
  text_extraction_method: 'pdf_text' | 'docx'
  profile: Record<string, any>
  skills: ResumeSkillRecord[]
}

export interface MatchRunReference {
  id: string
  owner_user_id: string
  resume_id: string
  resume_profile: {
    id: string
    version_no: number
  }
  graph_version: {
    id: string
    version_no?: number
  }
  catalog_version: {
    id: string
    version_no?: number
  }
  weight_version: string
  result_count: number
  high_count: number
  medium_count: number
  low_count: number
  created_at: string
}

export interface MatchDimensionScore {
  score: number
  status: string
  matched_count?: number
  total_count?: number
  matched_importance?: number
  total_importance?: number
  candidate_months?: number | null
  recommended_months?: number | null
  candidate_level?: string | null
  minimum_level?: string | null
  evidence_weighted_importance?: number
}

export interface MatchJobRoleSummary {
  id: string
  canonical_name: string
  description: string | null
  domain: {
    id: string
    code: string
    name: string
  }
}

export interface MatchResultListItem {
  job_role_id: string
  rank: number
  total_score: number
  match_level: 'high' | 'medium' | 'low'
  job_role: MatchJobRoleSummary
  dimension_scores: Record<
    'required_skill_coverage' | 'bonus_skill_coverage' | 'skill_evidence_quality' | 'experience' | 'education',
    MatchDimensionScore
  >
  gap_summary: {
    matched_required_count: number
    missing_required_count: number
    matched_bonus_count: number
    missing_bonus_count: number
  }
  created_at: string
}

export interface MatchResultPage {
  items: MatchResultListItem[]
  page: number
  page_size: number
  total: number
}

export interface RecommendationCreateResponse {
  reused: boolean
  run: MatchRunReference
  results: MatchResultPage
}

export interface MatchedCapability {
  capability_id: string
  canonical_name: string
  requirement_type: 'required' | 'bonus'
  importance: number
  resume_skill: {
    id: string
    raw_name: string
    mapping_method: 'canonical_exact' | 'alias_exact' | 'manual' | 'unmapped'
    evidence_strength: 'mention' | 'project' | 'work'
    evidence_quote: string | null
  }
}

export interface MissingCapability {
  capability_id: string
  canonical_name: string
  skill_type: string
  requirement_type: 'required' | 'bonus'
  importance: number
  domain: {
    id: string
    code: string
    name: string
  }
}

export interface RecommendationDetailResponse extends MatchResultListItem {
  job_role: MatchJobRoleSummary & {
    definition_payload: Record<string, any>
  }
  matched_capabilities: MatchedCapability[]
  missing_capabilities: MissingCapability[]
}

export interface GrowthCapability {
  id: string
  canonical_name: string
  skill_type: string
  domain: {
    id: string
    code: string
    name: string
  }
}

export interface GrowthStage {
  stage_no: number
  title: string
  objective: string
  capabilities: GrowthCapability[]
  estimated_weeks: number
  actions: string[]
  completion_criteria: string[]
}

export interface GrowthPlan {
  schema_version: 'growth_path_v1'
  target_role: MatchJobRoleSummary & {
    definition_payload: Record<string, any>
  }
  summary: string
  total_estimated_weeks: number
  stages: GrowthStage[]
  final_project: string
}

export interface GrowthPathRead {
  id: string
  match_run_id: string
  job_role_id: string
  prompt_version: 'growth_path_v1'
  source: {
    match_run: Record<string, any>
    match_result: Record<string, any>
  }
  plan: GrowthPlan
  created_at: string
}

export interface GrowthPathCreateResponse {
  reused: boolean
  growth_path: GrowthPathRead
}

function uploadProgressHandler(
  onUploadProgress?: (progress: number) => void,
) {
  if (!onUploadProgress) return undefined
  return (event: AxiosProgressEvent) => {
    if (!event.total) return
    onUploadProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
  }
}

export async function createResume(
  file: File,
  displayName?: string,
  onUploadProgress?: (progress: number) => void,
): Promise<ResumeCreateResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (displayName?.trim()) {
    formData.append('display_name', displayName.trim())
  }
  return request.upload<ResumeCreateResponse>('/api/v1/resumes', formData, {
    onUploadProgress: uploadProgressHandler(onUploadProgress),
  })
}

export async function getProcessingRun(runId: string): Promise<ProcessingRunResponse> {
  return request.get<ProcessingRunResponse>(`/api/v1/processing-runs/${runId}`)
}

export async function getProcessingRunResult(
  runId: string,
): Promise<ResumeProcessingResult> {
  return request.get(`/api/v1/processing-runs/${runId}/result`)
}

export async function getResumeProfile(
  resumeId: string,
  versionNo: number,
): Promise<ResumeProfileDetail> {
  return request.get<ResumeProfileDetail>(`/api/v1/resumes/${resumeId}/profiles/${versionNo}`)
}

export async function confirmResumeProfile(
  resumeId: string,
  versionNo: number,
): Promise<ResumeProfileDetail> {
  return request.post<ResumeProfileDetail>(`/api/v1/resumes/${resumeId}/profiles/${versionNo}/confirm`)
}

export async function createJobRecommendations(
  resumeId: string,
): Promise<RecommendationCreateResponse> {
  return request.post<RecommendationCreateResponse>('/api/v1/job-recommendations', {
    resume_id: resumeId,
  })
}

export async function getRecommendationDetail(
  matchRunId: string,
  jobRoleId: string,
): Promise<RecommendationDetailResponse> {
  return request.get<RecommendationDetailResponse>(
    `/api/v1/job-recommendations/${matchRunId}/job-roles/${jobRoleId}`,
  )
}

export async function createGrowthPath(
  matchRunId: string,
  jobRoleId: string,
): Promise<GrowthPathCreateResponse> {
  return request.post<GrowthPathCreateResponse>(
    `/api/v1/job-recommendations/${matchRunId}/job-roles/${jobRoleId}/growth-path`,
  )
}
