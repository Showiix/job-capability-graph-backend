import request from '../utils/request'
import type { EmergingJobsResponse } from '../types/api'

export function getEmergingJobs(params?: {
  query?: string
  industry?: string
  status?: string
  sort_by?: 'jdCount' | 'companyCount' | 'title'
}) {
  return request.get<EmergingJobsResponse>('/api/v1/emerging-jobs', { params })
}
