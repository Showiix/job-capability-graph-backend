import { useState, useRef } from 'react'
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { FrameCorners } from '../components/FrameCorners'

type Step = 0 | 1 | 2 | 3

// Mock 候选人数据
const MOCK_CANDIDATES = [
  {
    id: 'c1',
    name: '张三',
    match: 92,
    badge: 'A',
    education: '硕士',
    experience: '3-5年',
    skills: ['Python', 'PyTorch', 'Transformer', 'LangChain', 'RAG'],
    missingSkills: ['Kubernetes', 'MLflow'],
    status: 'uploaded',
  },
  {
    id: 'c2',
    name: '李四',
    match: 85,
    badge: 'A',
    education: '本科',
    experience: '5-10年',
    skills: ['Python', 'TensorFlow', 'Kubernetes', 'Docker', 'SQL'],
    missingSkills: ['Transformer', 'RAG', 'LangChain'],
    status: 'uploaded',
  },
  {
    id: 'c3',
    name: '王五',
    match: 78,
    badge: 'B',
    education: '硕士',
    experience: '1-3年',
    skills: ['Python', 'PyTorch', 'OpenCV', 'YOLO'],
    missingSkills: ['Transformer', 'NLP', 'LangChain', 'RAG'],
    status: 'uploaded',
  },
  {
    id: 'c4',
    name: '赵六',
    match: 68,
    badge: 'B',
    education: '本科',
    experience: '1-3年',
    skills: ['Java', 'Spring', 'MySQL', 'Redis'],
    missingSkills: ['Python', 'PyTorch', 'Transformer', 'AI基础'],
    status: 'uploaded',
  },
]

const HR_STEPS = ['创建项目', '批量上传', '候选排名', '对比分析']

// Ring chart component
function Ring({ v, size = 48, color = '#e4b592' }: { v: number; size?: number; color?: string }) {
  const r = (size - 6) / 2
  const c = 2 * Math.PI * r
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,243,234,0.12)" strokeWidth="4" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeDasharray={`${(v / 100) * c} ${c}`}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color})` }}
        />
      </svg>
      <div className="absolute font-jetbrains font-bold text-[11px]" style={{ color }}>
        {v}
      </div>
    </div>
  )
}

// Upload progress component
function UploadProgress({ files, progress }: { files: File[]; progress: number[] }) {
  return (
    <div className="space-y-2">
      {files.map((file, i) => (
        <div key={i} className="archive-row glass rounded-lg p-3 flex items-center gap-3">
          <div className="file-state-icon">
            {progress[i] === 100 ? <CheckCircleOutlined /> : <FileTextOutlined />}
          </div>
          <div className="flex-1">
            <div className="text-sm text-[var(--text)] mb-1">{file.name}</div>
            <div className="prog-track h-1">
              <div
                className="prog-fill transition-all duration-300"
                style={{
                  width: `${progress[i]}%`,
                  background: progress[i] === 100 ? '#dad0c8' : 'linear-gradient(90deg, #ee1212, #e4b592)',
                }}
              />
            </div>
          </div>
          <span className="font-jetbrains text-xs text-[var(--text-dim)]">{Math.round(progress[i])}%</span>
        </div>
      ))}
    </div>
  )
}

export default function HRWorkspacePage() {
  const [step, setStep] = useState<Step>(0)
  const [jobTitle, setJobTitle] = useState('')
  const [jobDescription, setJobDescription] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number[]>([])
  const [candidates] = useState(MOCK_CANDIDATES)
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([])
  const [sortBy, setSortBy] = useState<'match' | 'education' | 'experience'>('match')
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = (newFiles: FileList | null) => {
    if (!newFiles) return
    const fileArray = Array.from(newFiles)
    setFiles((prev) => [...prev, ...fileArray])
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDrag(false)
    handleFileSelect(e.dataTransfer.files)
  }

  const startBatchUpload = async () => {
    if (files.length === 0) return

    setUploading(true)
    const progress = Array.from({ length: files.length }, () => 0)
    setUploadProgress(progress)

    // Simulate upload progress for each file
    const intervals = files.map((_, index) => {
      return setInterval(() => {
        setUploadProgress((prev) => {
          const newProgress = [...prev]
          newProgress[index] = Math.min(newProgress[index] + Math.random() * 15 + 5, 100)
          if (newProgress[index] >= 100) {
            clearInterval(intervals[index])
          }
          return newProgress
        })
      }, 200)
    })

    // Wait for all uploads to complete
    setTimeout(() => {
      intervals.forEach((iv) => clearInterval(iv))
      setUploading(false)
      setStep(2)
    }, 3000)

    // TODO: 实际上传调用
    // for (const file of files) {
    //   await parseResume(file)
    // }
  }

  const toggleCandidate = (id: string) => {
    setSelectedCandidates((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    )
  }

  const getBadgeColor = (badge: string) => {
    switch (badge) {
      case 'A':
        return '#dad0c8'
      case 'B':
        return '#e4b592'
      case 'C':
        return '#ee1212'
      default:
        return '#a49b92'
    }
  }

  const sortedCandidates = [...candidates].sort((a, b) => {
    if (sortBy === 'match') return b.match - a.match
    if (sortBy === 'education') return a.education.localeCompare(b.education)
    return 0
  })

  return (
    <div className="page-shell page-shell--hr min-h-screen pt-14">
      <div className="page-shell__inner max-w-6xl mx-auto px-8 py-10">
        <div className="page-head page-head--archive">
          <FrameCorners />
          <div className="page-head__icon">
            <TeamOutlined />
          </div>
          <div className="page-head__copy">
            <div className="page-head__eyebrow">Hiring ops / candidate field</div>
            <h1 className="page-head__title">HR 工作台</h1>
            <p className="page-head__desc">解析 JD、批量处理简历，并把候选人按证据和匹配度排序。</p>
          </div>
        </div>

        {/* Stepper */}
        <div className="console-stepper archive-stepper mb-10">
          {HR_STEPS.map((label, i) => (
            <div key={label} className="console-stepper__item">
              <div
                className={`step-dot ${i < step ? 'step-done' : i === step ? 'step-active' : 'step-idle'}`}
                onClick={() => i < step && setStep(i as Step)}
                style={{ cursor: i < step ? 'pointer' : 'default' }}
              >
                {i < step ? '✓' : i + 1}
              </div>
              <div className="console-stepper__copy ml-2.5 flex-1 min-w-0">
                <div className="console-stepper__meta">STEP {String(i + 1).padStart(2, '0')}</div>
                <div
                  className="console-stepper__label font-inter font-semibold text-[13px]"
                  style={{ color: i === step ? 'var(--text)' : i < step ? '#dad0c8' : 'var(--text-dim)' }}
                >
                  {label}
                </div>
              </div>
              {i < 3 && (
                <div
                  className="console-stepper__line"
                  style={{ background: i < step ? 'linear-gradient(90deg,#dad0c8,#e4b592)' : 'var(--border)' }}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step 0: Create project */}
        {step === 0 && (
          <div className="hr-project-grid animate-fade-up">
            <div className="archive-panel hr-project-panel glass rounded-2xl p-8 max-w-2xl mx-auto">
              <FrameCorners />
              <h2 className="font-outfit font-bold text-xl text-[var(--text)] mb-6">创建招聘项目</h2>

              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">项目名称 / 岗位名称</label>
                  <input
                    type="text"
                    value={jobTitle}
                    onChange={(e) => setJobTitle(e.target.value)}
                    placeholder="例如：NLP 算法工程师（2024春招）"
                    className="w-full bg-[rgba(0,0,0,0.44)] border border-[var(--border)] px-4 py-3 text-[var(--text)] font-inter text-sm outline-none focus:border-[#e4b592] transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">岗位描述（JD）</label>
                  <textarea
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                    placeholder="粘贴完整的岗位描述，AI 将自动提取技能要求..."
                    rows={8}
                    className="w-full bg-[rgba(0,0,0,0.44)] border border-[var(--border)] px-4 py-3 text-[var(--text)] font-inter text-sm outline-none focus:border-[#e4b592] transition-colors resize-none"
                  />
                  <div className="text-xs text-[var(--text-dim)] mt-2">
                    可以点击「上传 JD 文件」直接上传 PDF/Word
                  </div>
                </div>

                <div className="flex gap-3 pt-4">
                  <button
                    className="btn btn-md btn-primary flex-1"
                    onClick={() => setStep(1)}
                    disabled={!jobTitle || !jobDescription}
                  >
                    解析 JD 并继续 <ArrowRightOutlined />
                  </button>
                  <button className="btn btn-md btn-ghost">
                    <FolderOpenOutlined />
                    上传 JD 文件
                  </button>
                </div>
              </div>
            </div>
            <aside className="hr-project-rail archive-panel glass">
              <FrameCorners />
              <div className="hr-project-rail__eyebrow">Hiring field / intake</div>
              <h2>招聘任务状态</h2>
              <div className="hr-project-rail__signal">
                <span className="hr-project-rail__signal-dot" />
                <div>
                  <strong>等待 JD</strong>
                  <span>项目尚未进入解析阶段</span>
                </div>
              </div>
              <div className="hr-project-rail__section">
                <span>解析后会生成</span>
                <ul>
                  <li>岗位技能基线</li>
                  <li>候选人批次</li>
                  <li>匹配证据</li>
                </ul>
              </div>
              <div className="hr-project-rail__footer">
                <span>UPLOAD WINDOW</span>
                <strong>01 - 50 RESUMES</strong>
              </div>
            </aside>
          </div>
        )}

        {/* Step 1: Batch upload */}
        {step === 1 && (
          <div className="animate-fade-up">
            <div className="archive-panel glass rounded-2xl p-8">
              <FrameCorners />
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="font-outfit font-bold text-xl text-[var(--text)]">批量上传候选人简历</h2>
                  <p className="text-sm text-[var(--text-dim)] mt-1">支持同时上传 1-50 份简历</p>
                </div>
                <div className="text-right">
                  <div className="font-jetbrains text-2xl font-bold text-space-cyan">{files.length}</div>
                  <div className="text-xs text-[var(--text-dim)]">已选择</div>
                </div>
              </div>

              {/* Upload area */}
              {!uploading && (
                <div
                    className={`console-dropzone archive-dropzone border-2 border-dashed p-10 text-center mb-6 transition-all cursor-pointer ${
                    drag ? 'border-[#e4b592] bg-[rgba(228,181,146,0.05)]' : 'border-[var(--border)]'
                  }`}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDrag(true)
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={handleDrop}
                  onClick={() => fileRef.current?.click()}
                >
                  <FrameCorners />
                  <div className="dropzone-icon">
                    <CloudUploadOutlined />
                  </div>
                  <div className="font-outfit font-bold text-lg text-[var(--text)] mb-2">
                    拖拽多个文件到这里
                  </div>
                  <div className="text-sm text-[var(--text-dim)]">或点击选择文件（支持多选）</div>
                  <div className="text-xs text-[#a49b92] mt-3">支持 PDF / Word · 单个文件最大 20 MB</div>
                </div>
              )}

              <input
                ref={fileRef}
                type="file"
                multiple
                className="hidden"
                accept=".pdf,.docx"
                onChange={(e) => handleFileSelect(e.target.files)}
              />

              {/* File list or upload progress */}
              {uploading ? (
                <UploadProgress files={files} progress={uploadProgress} />
              ) : files.length > 0 ? (
                <div className="space-y-2 mb-6">
                  {files.map((file, i) => (
                    <div key={i} className="archive-row glass rounded-lg p-3 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="file-state-icon">
                          <FileTextOutlined />
                        </span>
                        <div>
                          <div className="text-sm text-[var(--text)]">{file.name}</div>
                          <div className="text-xs text-[var(--text-dim)]">
                            {(file.size / 1024 / 1024).toFixed(2)} MB
                          </div>
                        </div>
                      </div>
                      <button
                        className="text-[var(--text-dim)] hover:text-[#ee1212] transition-colors"
                        onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                      >
                        <DeleteOutlined />
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}

              {/* Actions */}
              <div className="flex gap-3">
                <button className="btn btn-sm btn-ghost" onClick={() => setStep(0)}>
                  <ArrowLeftOutlined /> 返回
                </button>
                <button
                  className="btn btn-md btn-primary flex-1"
                  onClick={startBatchUpload}
                  disabled={files.length === 0 || uploading}
                >
                  {uploading ? '解析中...' : <>开始解析 {files.length} 份简历 <ArrowRightOutlined /></>}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Candidate ranking */}
        {step === 2 && (
          <div className="animate-fade-up">
            <div className="archive-panel glass rounded-2xl p-6 mb-6">
              <FrameCorners />
              <div className="flex justify-between items-center mb-4">
                <h2 className="font-outfit font-bold text-xl text-[var(--text)]">候选人排名</h2>
                <div className="flex gap-2">
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as any)}
                    className="bg-[rgba(0,0,0,0.44)] border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text)] outline-none cursor-pointer"
                  >
                    <option value="match">按匹配度排序</option>
                    <option value="education">按学历排序</option>
                    <option value="experience">按工作年限排序</option>
                  </select>
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={selectedCandidates.length < 2}
                    onClick={() => setStep(3)}
                  >
                    对比选中 ({selectedCandidates.length})
                  </button>
                </div>
              </div>

              {/* Candidate table */}
              <div className="space-y-3">
                {sortedCandidates.map((candidate, index) => (
                  <div
                    key={candidate.id}
                    className={`candidate-archive-row archive-row glass rounded-xl p-4 transition-all cursor-pointer ${
                      selectedCandidates.includes(candidate.id) ? 'ring-2 ring-space-cyan' : ''
                    }`}
                    onClick={() => toggleCandidate(candidate.id)}
                  >
                    <div className="hr-candidate-content flex items-center gap-4">
                      {/* Checkbox */}
                      <input
                        type="checkbox"
                        checked={selectedCandidates.includes(candidate.id)}
                        onChange={() => {}}
                        className="w-4 h-4"
                        style={{ accentColor: '#ee1212' }}
                      />

                      {/* Rank */}
                      <div className="text-center min-w-[40px]">
                        <div className="font-jetbrains font-bold text-2xl text-space-cyan">#{index + 1}</div>
                      </div>

                      {/* Match ring */}
                      <Ring v={candidate.match} size={56} color={getBadgeColor(candidate.badge)} />

                      {/* Info */}
                      <div className="hr-candidate-info flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-outfit font-bold text-base text-[var(--text)]">
                            {candidate.name}
                          </span>
                          <span
                            className="font-jetbrains text-[9px] px-2 py-0.5"
                            style={{
                              background: `${getBadgeColor(candidate.badge)}18`,
                              border: `1px solid ${getBadgeColor(candidate.badge)}40`,
                              color: getBadgeColor(candidate.badge),
                            }}
                          >
                            {candidate.badge}级
                          </span>
                          <span className="text-xs text-[var(--text-dim)]">
                            {candidate.education} · {candidate.experience}
                          </span>
                        </div>

                        {/* Skills */}
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {candidate.skills.slice(0, 5).map((skill) => (
                            <span key={skill} className="tag tag-green text-[10px]">
                              {skill}
                            </span>
                          ))}
                          {candidate.skills.length > 5 && (
                            <span className="text-xs text-[var(--text-dim)]">+{candidate.skills.length - 5}</span>
                          )}
                        </div>

                        {/* Missing skills */}
                        {candidate.missingSkills.length > 0 && (
                          <div className="text-xs text-[#ee1212]">
                            缺失: {candidate.missingSkills.slice(0, 3).join(', ')}
                            {candidate.missingSkills.length > 3 && ` +${candidate.missingSkills.length - 3}`}
                          </div>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="hr-candidate-actions flex gap-2">
                        <button className="btn btn-sm btn-ghost">查看详情</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <button className="btn btn-sm btn-ghost" onClick={() => setStep(1)}>
              <ArrowLeftOutlined /> 返回
            </button>
          </div>
        )}

        {/* Step 3: Compare candidates */}
        {step === 3 && selectedCandidates.length >= 2 && (
          <div className="animate-fade-up">
            <div className="archive-panel glass rounded-2xl p-6 mb-6">
              <FrameCorners />
              <h2 className="font-outfit font-bold text-xl text-[var(--text)] mb-6">候选人对比分析</h2>

              <div className="hr-compare-grid grid grid-cols-3 gap-4">
                {selectedCandidates.slice(0, 3).map((id) => {
                  const candidate = candidates.find((c) => c.id === id)
                  if (!candidate) return null

                  return (
                    <div key={id} className="archive-row glass rounded-xl p-5">
                      <div className="text-center mb-4">
                        <Ring v={candidate.match} size={72} color={getBadgeColor(candidate.badge)} />
                        <div className="font-outfit font-bold text-lg text-[var(--text)] mt-3">
                          {candidate.name}
                        </div>
                        <div className="text-xs text-[var(--text-dim)] mt-1">
                          {candidate.education} · {candidate.experience}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <div className="text-xs font-medium text-[var(--text-dim)] mb-1.5">
                            <CheckCircleOutlined /> 已具备技能
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {candidate.skills.map((s) => (
                              <span key={s} className="tag tag-green text-[10px]">
                                {s}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div>
                          <div className="text-xs font-medium text-[var(--text-dim)] mb-1.5">
                            <CloseCircleOutlined /> 缺失技能
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {candidate.missingSkills.map((s) => (
                              <span key={s} className="tag tag-red text-[10px]">
                                {s}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="hr-final-actions flex gap-3">
              <button className="btn btn-sm btn-ghost" onClick={() => setStep(2)}>
                <ArrowLeftOutlined /> 返回列表
              </button>
              <button className="btn btn-sm btn-primary">
                <DownloadOutlined /> 导出对比报告
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
