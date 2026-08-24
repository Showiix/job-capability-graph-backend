import request from '../utils/request';
import type {
  GraphData,
  ResumeParseResult,
  JobParseResult,
  MatchResult,
  StatsData,
  JobRankResult,
  NewJob,
  HrBatchParseResult,
  LearningPathResult,
  AdminPendingResult,
  AdminLogsResult,
  Skill,
} from '../types/api';

// 获取图谱数据
export const getGraphData = (params?: { category?: string; level?: string }) => {
  return request.get<GraphData>('/api/graph', { params });
};

// 解析简历
export const parseResume = (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return request.upload<ResumeParseResult>('/api/resume/parse', formData);
};

// 解析岗位描述
export const parseJobDescription = (text: string) => {
  return request.post<JobParseResult>('/api/jd/parse', { text });
};

// 人岗匹配
export const matchJobSkills = (userSkills: Skill[], jobId: string) => {
  return request.post<MatchResult>('/api/match', {
    user_skills: userSkills,
    job_id: jobId,
  });
};

// 首页统计看板数据
export const getStats = () => {
  return request.get<StatsData>('/api/stats');
};

// 应聘者技能与全部岗位匹配排名
export const rankJobs = (userSkills: Skill[]) => {
  return request.post<JobRankResult>('/api/match/rank', {
    user_skills: userSkills,
  });
};

// 新岗位候选列表
export const getNewJobs = () => {
  return request.get<NewJob[]>('/api/new-jobs');
};

// HR 审核新岗位（采纳/修改/拒绝）
export const reviewNewJob = (
  jobId: string,
  action: 'approve' | 'modify' | 'reject',
  payload?: Partial<NewJob>,
) => {
  return request.post<{ success: boolean }>('/api/new-jobs/review', {
    job_id: jobId,
    action,
    payload,
  });
};

// HR 批量简历解析
export const hrBatchParse = (files: File[]) => {
  const formData = new FormData();
  files.forEach((f) => formData.append('files', f));
  return request.upload<HrBatchParseResult>('/api/hr/batch-parse', formData);
};

// 应聘者自定义技能提交（后台审核）
export const submitSkillSupplement = (name: string) => {
  return request.post<{ status: 'pending' }>('/api/applicant/skill-supplement', {
    name,
  });
};

// 学习路径生成（LangChain）
export const getLearningPath = (skills: string[]) => {
  return request.get<LearningPathResult>('/api/learning-path', {
    params: { skills: skills.join(',') },
  });
};

// 审核后台：待审核队列
export const getAdminPending = () => {
  return request.get<AdminPendingResult>('/api/admin/pending');
};

// 审核后台：批准/拒绝操作
export const adminApprove = (
  type: 'new_job' | 'custom_skill',
  id: string,
  action: 'approve' | 'reject',
) => {
  return request.post<{ success: boolean }>('/api/admin/approve', {
    type,
    id,
    action,
  });
};

// 审核后台：操作日志
export const getAdminLogs = () => {
  return request.get<AdminLogsResult>('/api/admin/logs');
};
