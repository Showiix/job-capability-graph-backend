// API接口类型定义
export interface ApiResponse<T = any> {
  code: number;
  data: T;
  message: string;
}

// 图谱节点类型
export interface GraphNode {
  id: string;
  label: string;
  type: 'job' | 'skill';
  level?: '基础' | '核心' | '前沿';
  is_new?: boolean;
  effective_count?: number;
  category?: '传统技术' | 'AI新兴技能';
  status?: string;
  dynamic_status?: 'skill_emerging' | 'skill_declining' | 'skill_upgraded' | null;
  is_inflated?: boolean;
  change_history?: Array<{
    job: string;
    change_type: string;
    confidence: number;
    effect_size: number;
  }>;
}

// 图谱边类型
export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  relation?: string;
}

// 图谱数据
export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// 图谱统计数据
export interface GraphStats {
  stable: number;
  growing: number;
  emerging: number;
  by_category: { '传统技术': number; 'AI新兴技能': number };
  inflated_skills: number;
  dynamic: { skill_emerging: number; skill_declining: number; skill_upgraded: number };
}

// 首页统计数据
export interface StatsData {
  job_count: number;
  skill_count: number;
  last_updated: string;
  match_count: number;
}

// 技能项
export interface Skill {
  name: string;
  level: '基础' | '核心' | '前沿';
  proficiency: number;
  weight?: number;
}

// 简历解析结果
export interface ResumeParseResult {
  name: string;
  skills: Skill[];
}

// 岗位描述解析结果
export interface JobParseResult {
  job_title: string;
  job_id: string;
  required_skills: Skill[];
}

// 证据来源（RAG 防控）
export interface Evidence {
  jd_count: number;
  confidence: number; // 0-1
}

// 差距技能项（含证据来源）
export interface GapSkill {
  name: string;
  level: string;
  required_proficiency: number;
  user_proficiency: number;
  weight?: number;
  evidence?: Evidence;
}

// 匹配结果
export interface MatchResult {
  job_name?: string;
  match_score: number;
  matched_skills: Skill[];
  gap_skills: GapSkill[];
  // 加分技能中缺失（可选，用于四分类差距）
  bonus_gap_skills?: GapSkill[];
  // 额外技能：用户具备但岗位未要求
  extra_skills?: Skill[];
  // 雷达图维度：必备/加分/工具
  radar?: {
    dimensions: string[];
    user: number[];
    required: number[];
  };
}

// 岗位匹配排名项（应聘者侧：与全部岗位匹配）
export interface JobRankItem {
  job_id: string;
  job_name: string;
  match_score: number; // 0-1
  matched_count: number;
  required_count: number;
}

// 应聘者侧全岗位匹配结果
export interface JobRankResult {
  jobs: JobRankItem[];
}

// 新岗位候选
export interface NewJob {
  id: string;
  title: string;
  confidence: number; // 0-100
  category: string;
  required_skills: string[];
  bonus_skills?: string[];
  source_count: number;
  generated_at: string;
  responsibilities?: string;
  scene?: string;
  status?: 'pending' | 'approved' | 'rejected' | 'editing';
  // RAG 证据来源列表
  evidences?: Array<{ jd_title: string; source: string; snippet: string }>;
}

export interface EmergingSkillDefinition {
  name: string;
  percentage: number | null;
}

export interface EmergingJobDefinition {
  id: string;
  title: string;
  normalizedName: string;
  aliases: string[];
  jdCount: number;
  removedCloneCount: number;
  companyCount: number;
  responsibilities: string[];
  requiredSkills: EmergingSkillDefinition[];
  bonusSkills: EmergingSkillDefinition[];
  requiredTechnicalText: string;
  bonusTechnicalText: string;
  industryScenes: string[];
  primaryIndustry: string;
  representativeCompanies: string[];
  cities: string[];
  llmRefined: boolean;
  reviewStatus: string;
  reviewStatusCode: 'pending' | 'approved' | 'rejected';
  reviewNote: string;
}

export interface EmergingJobsResponse {
  version: string;
  sourceFiles: string[];
  summary: {
    definitionCount: number;
    sourceDefinitionCount?: number;
    totalJdCount: number;
    totalRemovedCloneCount: number;
    averageJdPerDefinition: number;
    skillCount: number;
    statusCounts: Record<string, number>;
    industryStats: Array<{ name: string; jdCount: number; definitionCount: number }>;
    topSkills: Array<{
      name: string;
      definitionCount: number;
      requiredCount: number;
      bonusCount: number;
    }>;
  };
  jobs: EmergingJobDefinition[];
  total?: number;
}

// HR 批量简历解析结果
export interface HrBatchApplicant {
  id: string;
  name: string;
  file: string;
  status: 'parsing' | 'done' | 'failed';
  experience?: string;
  education?: string;
  skills: string[];
}

export interface HrBatchParseResult {
  applicants: HrBatchApplicant[];
}

// 学习路径
export interface LearningPathStep {
  title: string;
  duration: string;
  resource_url?: string;
  resource_name?: string;
}

export interface LearningPathItem {
  skill: string;
  level: string;
  steps: LearningPathStep[];
}

export interface LearningPathResult {
  paths: LearningPathItem[];
}

// 审核后台 - 待审核项
export interface PendingItem {
  id: string;
  type: 'new_job' | 'custom_skill';
  title: string;
  submitter?: string;
  submitted_at: string;
  confidence?: number;
  detail?: string;
}

export interface AdminPendingResult {
  items: PendingItem[];
}

// 审核后台 - 操作日志
export interface AdminLog {
  id: string;
  operator: string;
  time: string;
  action: string;
  target: string;
}

export interface AdminLogsResult {
  logs: AdminLog[];
}

// 认证 - 当前用户
export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  role: 'admin' | 'hr' | 'applicant';
  is_active: boolean;
}
