import { useRef, useState } from 'react'
import type { CSSProperties, PointerEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { NodeIndexOutlined } from '@ant-design/icons'
import moonImage from '../assets/apollo-moon.jpg'
import graphImage from '../assets/archive-graph.png'
import resumeImage from '../assets/archive-resume.png'
import hiringImage from '../assets/archive-hiring.png'
import trendsImage from '../assets/archive-trends.png'

type ArchiveAction = {
  id: string
  path: string
  image: string
  meta: string
  title: string
  coord: string
}

const ARCHIVE_ACTIONS: ArchiveAction[] = [
  {
    id: 'graph',
    path: '/graph',
    image: graphImage,
    meta: 'GALLERY 01',
    title: '3D 知识图谱',
    coord: 'ORBIT MAP',
  },
  {
    id: 'applicant',
    path: '/applicant',
    image: resumeImage,
    meta: 'GALLERY 02',
    title: '简历评估',
    coord: 'RESUME SCAN',
  },
  {
    id: 'hr',
    path: '/hr',
    image: hiringImage,
    meta: 'GALLERY 03',
    title: 'HR 工作台',
    coord: 'HIRING OPS',
  },
  {
    id: 'emerging',
    path: '/emerging',
    image: trendsImage,
    meta: 'GALLERY 04',
    title: '新兴岗位',
    coord: 'MARKET RADAR',
  },
]

function Starfield() {
  const stars = useRef(
    Array.from({ length: 170 }, (_, index) => ({
      x: (Math.sin(index * 19.37) * 10000) % 100,
      y: (Math.cos(index * 13.11) * 10000) % 100,
      s: index % 19 === 0 ? 2 : 1,
      o: 0.16 + ((index * 37) % 60) / 100,
      dur: 2.6 + (index % 7) * 0.38,
      del: (index % 13) * 0.18,
    }))
  )

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {stars.current.map((s, i) => (
        <span
          key={i}
          className="absolute bg-[#fff3ea] animate-twinkle"
          style={{
            left: `${Math.abs(s.x)}%`,
            top: `${Math.abs(s.y)}%`,
            width: s.s,
            height: s.s,
            opacity: s.o,
            animationDuration: `${s.dur}s`,
            animationDelay: `${s.del}s`,
          }}
        />
      ))}
    </div>
  )
}

export default function SpaceHomePage() {
  const navigate = useNavigate()
  const archiveRef = useRef<HTMLElement>(null)
  const [activeActionId, setActiveActionId] = useState(ARCHIVE_ACTIONS[0].id)
  const activeAction = ARCHIVE_ACTIONS.find((action) => action.id === activeActionId) ?? ARCHIVE_ACTIONS[0]

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
    event.currentTarget.style.setProperty('--focus-x', `${x * 100}%`)
    event.currentTarget.style.setProperty('--focus-y', `${y * 100}%`)
    event.currentTarget.style.setProperty('--moon-x', `${(0.5 - x) * 46}px`)
    event.currentTarget.style.setProperty('--moon-y', `${(0.5 - y) * 30}px`)
    event.currentTarget.style.setProperty('--photo-tilt-x', `${(0.5 - y) * 2.6}deg`)
    event.currentTarget.style.setProperty('--photo-tilt-y', `${(x - 0.5) * 4.2}deg`)
    event.currentTarget.style.setProperty('--photo-drift-x', `${(x - 0.5) * 18}px`)
    event.currentTarget.style.setProperty('--photo-drift-y', `${(y - 0.5) * 12}px`)
    event.currentTarget.style.setProperty('--scan-opacity', '1')
  }

  const resetFocus = () => {
    const node = archiveRef.current
    if (!node) return
    node.style.setProperty('--focus-x', '52%')
    node.style.setProperty('--focus-y', '46%')
    node.style.setProperty('--moon-x', '-0.92px')
    node.style.setProperty('--moon-y', '1.2px')
    node.style.setProperty('--photo-tilt-x', '0.104deg')
    node.style.setProperty('--photo-tilt-y', '0.084deg')
    node.style.setProperty('--photo-drift-x', '0.36px')
    node.style.setProperty('--photo-drift-y', '-0.48px')
    node.style.setProperty('--scan-opacity', '0.68')
  }

  const focusStyle = {
    '--focus-x': '52%',
    '--focus-y': '46%',
    '--moon-x': '-0.92px',
    '--moon-y': '1.2px',
    '--photo-tilt-x': '0.104deg',
    '--photo-tilt-y': '0.084deg',
    '--photo-drift-x': '0.36px',
    '--photo-drift-y': '-0.48px',
    '--scan-opacity': '0.68',
  } as CSSProperties

  const openArchive = (action: ArchiveAction) => {
    navigate(action.path)
  }

  return (
    <div className="space-home min-h-screen relative overflow-hidden">
      <Starfield />
      <div className="space-home__grid" />

      <section
        ref={archiveRef}
        className="moon-archive"
        style={focusStyle}
        onPointerMove={handlePointerMove}
        onPointerLeave={resetFocus}
      >
        <div className="moon-archive__viewfinder" aria-hidden />
        <div className="moon-archive__scanbeam" aria-hidden />
        <div className="moon-archive__compass" aria-hidden>
          <span>AZ 042</span>
          <span>FOCUS SERVO</span>
          <span>EL 118</span>
        </div>
        <div className="moon-archive__meter" aria-hidden>
          {Array.from({ length: 12 }, (_, index) => (
            <span key={index} style={{ '--meter-index': index } as CSSProperties} />
          ))}
        </div>
        <div className="moon-archive__copy">
          <div className="section-kicker">
            <span />
            Archive / 001
          </div>
          <h1>
            岗位能力
            <span>月面档案</span>
          </h1>
          <div className="moon-archive__copy-readout">
            <span>FIELD STUDY</span>
            <span>40.7128 N / 74.0060 W</span>
          </div>
        </div>

        <div className="moon-stage" aria-hidden={false}>
          <div className="moon-stage__rings" />
          <button
            className="moon-stage__moon"
            onClick={() => openArchive(activeAction)}
            aria-label={`打开${activeAction.title}`}
          >
            <img src={moonImage} alt="月球表面档案主视觉" />
            <span className="moon-stage__moon-target">
              <span>ACTIVE TARGET</span>
              <strong>{activeAction.title}</strong>
            </span>
            <span className="moon-stage__moon-label">
              <NodeIndexOutlined /> OPEN {activeAction.coord}
            </span>
          </button>
          <div className="moon-archive__focus" aria-hidden />
        </div>

        <div className="archive-photo-field" aria-label="档案入口">
          {ARCHIVE_ACTIONS.map((action) => (
            <button
              key={action.id}
              className={`archive-photo archive-photo--${action.id} ${
                activeAction.id === action.id ? 'archive-photo--active' : ''
              }`}
              onPointerEnter={() => setActiveActionId(action.id)}
              onFocus={() => setActiveActionId(action.id)}
              onClick={() => openArchive(action)}
              aria-label={`打开${action.title}`}
            >
              <span className="archive-photo__frame">
                <img src={action.image} alt="" />
              </span>
              <span className="archive-photo__meta">
                {action.meta}
              </span>
              <strong>{action.title}</strong>
              <em>{action.coord}</em>
              <span className="archive-photo__cue">ENTER ARCHIVE</span>
            </button>
          ))}
        </div>

      </section>
    </div>
  )
}
