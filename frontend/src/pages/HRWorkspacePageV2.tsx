import { useState } from 'react'
import { ArrowRightOutlined, CloudUploadOutlined, TeamOutlined } from '@ant-design/icons'
import { Alert, Button, Input, List, Tag, Upload } from 'antd'
import type { UploadFile } from 'antd'
import { FrameCorners } from '../components/FrameCorners'
import {
  confirmRecruitmentRequirements,
  createRecruitmentMatchRun,
  createRecruitmentProject,
  getProcessingRun,
  getRecruitmentProject,
  listRecruitmentMatchResults,
  submitRecruitmentJd,
  uploadRecruitmentCandidates,
} from '../services/resumeWorkflowApi'

const { Dragger } = Upload

export default function HRWorkspacePageV2() {
  const [title, setTitle] = useState('')
  const [jd, setJd] = useState('')
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [projectId, setProjectId] = useState<string | null>(null)
  const [status, setStatus] = useState('等待输入岗位 JD')
  const [working, setWorking] = useState(false)
  const [result, setResult] = useState<any[]>([])

  async function waitRun(runId: string) {
    for (;;) {
      const state = await getProcessingRun(runId)
      if (state.status === 'completed') return
      if (['failed', 'cancelled'].includes(state.status)) throw new Error(state.error_message ?? '任务失败')
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  }

  async function parseJd() {
    if (!title.trim() || !jd.trim()) return
    setWorking(true)
    try {
      setStatus('创建招聘项目并解析 JD…')
      const project = await createRecruitmentProject(title.trim())
      setProjectId(project.id)
      const run = await submitRecruitmentJd(project.id, jd)
      await waitRun(run.run_id)
      const parsed = await getRecruitmentProject(project.id)
      await confirmRecruitmentRequirements(project.id, parsed.jd_draft_payload)
      setStatus('JD 已确认，可以上传候选人简历')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'JD 解析失败')
    } finally {
      setWorking(false)
    }
  }

  async function uploadCandidates() {
    const files = fileList.flatMap((item) => item.originFileObj ? [item.originFileObj as File] : [])
    if (!projectId || files.length === 0) return
    setWorking(true)
    try {
      setStatus(`正在解析 ${files.length} 份候选人简历…`)
      const run = await uploadRecruitmentCandidates(projectId, files)
      await waitRun(run.run_id)
      setStatus('候选人解析完成，可以开始匹配')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '候选人解析失败')
    } finally {
      setWorking(false)
    }
  }

  async function matchCandidates() {
    if (!projectId) return
    setWorking(true)
    try {
      setStatus('正在调用 graph_match_v1.0…')
      const run = await createRecruitmentMatchRun(projectId)
      const rows = await listRecruitmentMatchResults(projectId, run.run.id)
      setResult(rows.data ?? [])
      setStatus('匹配完成')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '匹配失败')
    } finally {
      setWorking(false)
    }
  }

  return <div className="page-shell page-shell--hr min-h-screen pt-14"><div className="page-shell__inner max-w-6xl mx-auto px-8 py-10"><header className="page-head page-head--archive"><FrameCorners /><div className="page-head__icon"><TeamOutlined /></div><div className="page-head__copy"><div className="page-head__eyebrow">Hiring ops / real backend</div><h1 className="page-head__title">HR 工作台</h1><p className="page-head__desc">录入岗位需求，批量解析候选人简历，并查看真实匹配结果。</p></div></header><section className="archive-panel glass max-w-4xl mx-auto p-8"><FrameCorners /><div className="flex flex-col gap-5"><div><h2 className="text-xl font-semibold">岗位需求</h2><p className="mt-1 text-sm text-[var(--text-dim)]">先确认岗位 JD，再进入候选人筛选。</p></div><Input size="large" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="岗位名称" aria-label="岗位名称" disabled={Boolean(projectId)} /><Input.TextArea value={jd} onChange={(event) => setJd(event.target.value)} placeholder="粘贴岗位职责、任职要求和技能要求" autoSize={{ minRows: 8, maxRows: 14 }} aria-label="岗位 JD" disabled={Boolean(projectId)} />{!projectId ? <Button type="primary" size="large" icon={<ArrowRightOutlined />} loading={working} disabled={!title.trim() || !jd.trim()} onClick={() => void parseJd()}>解析并确认 JD</Button> : <><Dragger multiple accept=".pdf,.docx,.jpg,.jpeg,.png" fileList={fileList} beforeUpload={() => false} onChange={({ fileList: next }) => setFileList(next)}><p className="ant-upload-drag-icon"><CloudUploadOutlined /></p><p className="ant-upload-text">选择或拖入候选人简历</p><p className="ant-upload-hint">支持 PDF、DOCX、JPG、PNG，可一次上传多份</p></Dragger><div className="flex flex-wrap gap-3"><Button type="primary" loading={working} disabled={!fileList.length} onClick={() => void uploadCandidates()}>上传并解析 {fileList.length} 份简历</Button><Button loading={working} onClick={() => void matchCandidates()}>开始候选人匹配</Button></div></>}<Alert type={status.includes('失败') ? 'error' : 'info'} showIcon message={status} />{result.length > 0 && <div><h2 className="mb-3 text-xl font-semibold">匹配结果</h2><List bordered dataSource={result} renderItem={(row: any) => <List.Item><List.Item.Meta title={<span className="text-base">#{row.rank} {row.candidate?.display_name ?? row.candidate_id}</span>} description={`缺失能力：${(row.missing_capabilities ?? []).map((item: any) => item.canonical_name).join('、') || '无'}`} /><Tag color="orange">匹配分 {row.total_score}</Tag></List.Item>} /></div>}</div></section></div></div>
}
