import request from '../utils/request'

export interface ReviewProposal { id: string; review_status: string; change_type: string; proposed_payload: Record<string, any>; created_at: string }
export interface AdminUser { id: string; username: string; display_name: string; role: string; is_active: boolean; created_at: string }

export const listReviewProposals = (status = 'pending') => request.get<ReviewProposal[]>(`/api/v1/review-proposals?status=${status}`)
export const decideReviewProposal = (id: string, decision: 'approve' | 'revise' | 'reject', comment: string, after_payload?: Record<string, any>) => request.post(`/api/v1/review-proposals/${id}/decisions`, { decision, comment, after_payload })
export const listAdminUsers = () => request.get<{ items: AdminUser[]; total: number }>('/api/v1/admin/users')
export const getSystemDependencies = () => request.get<Record<string, string>>('/api/v1/admin/system/dependencies')
export const getSystemVersions = () => request.get<Record<string, any>>('/api/v1/admin/system/versions')
export const listApprovedProposals = () => request.get<ReviewProposal[]>('/api/v1/review-proposals?status=approved')
export const createGraphVersion = (proposalId: string) => request.post<any>('/api/v1/graph-versions', { proposal_id: proposalId })
export const publishGraphVersion = (versionId: string) => request.post<any>(`/api/v1/graph-versions/${versionId}/publish`)
export const listImports = () => request.get<any[]>('/api/v1/imports')
export const listCatalogImports = () => request.get<any[]>('/api/v1/catalog/imports')
export const uploadCatalog = (file: File, importType: 'capability' | 'job_role') => { const form = new FormData(); form.append('file', file); form.append('import_type', importType); form.append('schema_version', 'catalog_v1'); form.append('mode', 'apply'); return request.upload('/api/v1/catalog/imports', form) }
export const createDiscoveryRun = (batchId: string) => request.post('/api/v1/discovery-runs', { batch_ids: [batchId], minimum_support_jobs: 2, minimum_source_count: 1, minimum_quality_score: 60, maximum_candidates: 50 })
export const listDiscoveryRuns = () => request.get<any[]>('/api/v1/discovery-runs')
