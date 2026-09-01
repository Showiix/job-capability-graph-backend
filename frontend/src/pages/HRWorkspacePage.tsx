import { useState } from 'react'
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'
import FadeContent from '../components/reactbits/FadeContent/FadeContent'
import CountUp from '../components/reactbits/CountUp/CountUp'
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

type CandidateRow = {
  candidate_id: string
  rank: number
  total_score: number
  candidate?: { display_name?: string }
  missing_capabilities?: { canonical_name: string }[]
}

const PIPELINE_STEPS = ['JD 解析', '候选人解析', '能力匹配']

function clampScore(value: number) {
  return Math.max(0, Math.min(100, value))
}

function scoreColor(value: number) {
  if (value >= 75) return '#dad0c8'
  if (value >= 50) return '#e4b592'
  return '#ee1212'
}

export default function HRWorkspacePage() {
  const [title, setTitle] = useState('')
  const [jd, setJd] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [projectId, setProjectId] = useState<string | null>(null)
  const [status, setStatus] = useState('等待 JD')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<CandidateRow[] | null>(null)

  const rows = result ?? []

  const waitRun = async (runId: string) => {
    for (;;) {
      const state = await getProcessingRun(runId)
      if (state.status === 'completed') return
      if (['failed', 'cancelled'].includes(state.status)) throw new Error(state.error_message ?? '任务失败')
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  }

  const parseJd = async () => {
    if (!title.trim() || !jd.trim() || busy) return
    setBusy(true)
    try {
      setStatus('创建项目并解析 JD...')
      const project = await createRecruitmentProject(title.trim())
      setProjectId(project.id)
      const run = await submitRecruitmentJd(project.id, jd)
      await waitRun(run.run_id)
      const parsed = await getRecruitmentProject(project.id)
      await confirmRecruitmentRequirements(project.id, parsed.jd_draft_payload)
      setStatus('JD 已解析并确认，可上传候选人')
    } finally {
      setBusy(false)
    }
  }

  const upload = async () => {
    if (!projectId || !files.length || busy) return
    setBusy(true)
    try {
      setStatus('上传并解析候选人...')
      const run = await uploadRecruitmentCandidates(projectId, files)
      await waitRun(run.run_id)
      setStatus('候选人解析完成，可开始匹配')
    } finally {
      setBusy(false)
    }
  }

  const match = async () => {
    if (!projectId || busy) return
    setBusy(true)
    try {
      setStatus('调用 graph_match_v1.0 匹配...')
      const response = await createRecruitmentMatchRun(projectId)
      const data = await listRecruitmentMatchResults(projectId, response.run.id)
      const list = Array.isArray(data) ? data : (data as { data?: CandidateRow[] })?.data ?? []
      setResult(list)
      setStatus('匹配完成')
    } finally {
      setBusy(false)
    }
  }

  const currentStep = result ? 3 : rows.length >= 0 && result === null && projectId && status.includes('匹配完成') ? 2 : projectId ? 1 : 0

  return (
    <div className="page-shell page-shell--hr min-h-screen pt-14">
      <div className="page-shell__inner max-w-6xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive">
          <FrameCorners />
          <div className="page-head__icon"><TeamOutlined /></div>
          <div className="page-head__copy">
            <div className="page-head__eyebrow">Hiring ops / real backend</div>
            <h1 className="page-head__title">HR 工作台</h1>
            <p className="page-head__desc">JD 解析、候选人解析与 graph_match_v1.0 排名。</p>
          </div>
        </div>

        <FadeContent duration={650} threshold={0.05}>
          <div className="hr-console archive-panel glass">
            <FrameCorners />
            <div className="hr-console__head">
              <span className="hr-console__kicker">HIRING PIPELINE / GRAPH MATCH V1.0</span>
              <span className="hr-console__status">
                <i className={busy ? 'is-busy' : ''} />
                {status}
              </span>
            </div>

            <div className="console-stepper archive-stepper hr-stepper">
              {PIPELINE_STEPS.map((label, i) => {
                const done = currentStep > i
                const active = currentStep === i
                return (
                  <div key={label} className="console-stepper__item">
                    <div className={`step-dot ${done ? 'step-done' : active ? 'step-active' : 'step-idle'}`}>
                      {done ? '✓' : i + 1}
                    </div>
                    <div className="console-stepper__copy ml-2.5 flex-1 min-w-0">
                      <div className="console-stepper__meta">STEP {String(i + 1).padStart(2, '0')}</div>
                      <div className="console-stepper__label font-inter font-semibold text-[13px]">{label}</div>
                    </div>
                    {i < PIPELINE_STEPS.length - 1 && (
                      <div
                        className="console-stepper__line"
                        style={{ background: done ? 'linear-gradient(90deg,#dad0c8,#e4b592)' : 'var(--border)' }}
                      />
                    )}
                  </div>
                )
              })}
            </div>

            <div className="hr-console__grid">
              <section className="hr-section">
                <header className="hr-section__head">
                  <span className="hr-section__index">01</span>
                  <div>
                    <h2>岗位 JD 解析</h2>
                    <em>JOB REQUIREMENT PARSING</em>
                  </div>
                  {projectId && <span className="tag tag-green hr-section__badge"><CheckCircleOutlined /> 已确认</span>}
                </header>

                <label className="hr-field">
                  <span>岗位名称</span>
                  <input
                    className="archive-control"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="例如：大模型算法工程师"
                    disabled={!!projectId}
                  />
                </label>

                <label className="hr-field hr-field--grow">
                  <span>岗位 JD</span>
                  <textarea
                    className="archive-control"
                    value={jd}
                    onChange={(e) => setJd(e.target.value)}
                    placeholder="粘贴完整岗位描述，后端将抽取必备/加分能力..."
                    rows={8}
                    disabled={!!projectId}
                  />
                </label>

                <button className="btn btn-primary hr-section__action" onClick={() => void parseJd()} disabled={!title || !jd || !!projectId || busy}>
                  解析 JD <ArrowRightOutlined />
                </button>
              </section>

              <section className={`hr-section ${!projectId ? 'hr-section--pending' : ''}`}>
                <header className="hr-section__head">
                  <span className="hr-section__index">02</span>
                  <div>
                    <h2>候选人简历</h2>
                    <em>CANDIDATE INTAKE</em>
                  </div>
                  {files.length > 0 && <span className="hr-section__badge tag tag-blue">{files.length} 份文件</span>}
                </header>

                {projectId ? (
                  <>
                    <label className="console-dropzone hr-dropzone">
                      <CloudUploadOutlined className="text-2xl" />
                      <strong>选择候选人简历</strong>
                      <span>支持 PDF / DOCX，可多选</span>
                      <input
                        type="file"
                        multiple
                        accept=".pdf,.docx"
                        className="hidden"
                        onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                      />
                    </label>
                    <div className="hr-section__actions">
                      <button className="btn btn-primary" onClick={() => void upload()} disabled={!files.length || busy}>
                        上传并解析
                      </button>
                      <button className="btn btn-ghost" onClick={() => void match()} disabled={busy}>
                        开始匹配 <ArrowRightOutlined />
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="hr-pending-note">
                    <FileSearchOutlined />
                    <span>完成第 01 步 JD 解析后，此处开放候选人上传。</span>
                  </div>
                )}
              </section>
            </div>
          </div>
        </FadeContent>

        {result && (
          <FadeContent duration={700} delay={0.1} threshold={0.03}>
            <section className="hr-results archive-panel glass">
              <FrameCorners />
              <header className="hr-results__head">
                <div>
                  <span className="hr-console__kicker">MATCH RANKING / graph_match_v1.0</span>
                  <h2>候选人排名</h2>
                </div>
                <strong><CountUp to={rows.length} duration={0.9} /> 位候选人</strong>
              </header>

              <div className="hr-results__list">
                {rows.map((row) => {
                  const score = clampScore(Number(row.total_score) || 0)
                  const color = scoreColor(score)
                  const missing = row.missing_capabilities ?? []
                  return (
                    <article key={row.candidate_id} className="hr-candidate archive-row">
                      <span className="hr-candidate__rank" style={{ borderColor: `${color}66`, color }}>#{row.rank}</span>
                      <div className="hr-candidate__main">
                        <strong>{row.candidate?.display_name ?? row.candidate_id}</strong>
                        <div className="hr-candidate__scoreline">
                          <div className="prog-track">
                            <div className="prog-fill" style={{ width: `${score}%`, background: color }} />
                          </div>
                          <em style={{ color }}><CountUp to={score} duration={1.3} /></em>
                        </div>
                        <div className="hr-candidate__gaps">
                          <span><DatabaseOutlined /> 缺失能力</span>
                          {missing.length ? (
                            missing.map((item) => (
                              <span key={item.canonical_name} className="tag tag-red">{item.canonical_name}</span>
                            ))
                          ) : (
                            <span className="hr-candidate__none">无缺失</span>
                          )}
                        </div>
                      </div>
                    </article>
                  )
                })}
                {rows.length === 0 && (
                  <div className="hr-pending-note">
                    <TeamOutlined />
                    <span>本次匹配没有返回候选人。</span>
                  </div>
                )}
              </div>
            </section>
          </FadeContent>
        )}
      </div>
    </div>
  )
}
