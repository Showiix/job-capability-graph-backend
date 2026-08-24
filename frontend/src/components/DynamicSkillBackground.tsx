import { useEffect, useRef } from 'react'

type Strand = {
  base: number
  amplitude: number
  frequency: number
  phase: number
  speed: number
  color: string
  alpha: number
  width: number
  drift: number
}

type Particle = {
  strand: number
  offset: number
  speed: number
  size: number
  alpha: number
}

const TAU = Math.PI * 2
const STRAND_COLORS = ['255, 243, 234', '228, 181, 146', '218, 208, 200', '238, 18, 18']

const seeded = (index: number, salt: number) => {
  const value = Math.sin(index * 127.1 + salt * 311.7) * 43758.5453
  return value - Math.floor(value)
}

const createStrands = (): Strand[] =>
  Array.from({ length: 13 }, (_, index) => ({
    base: 0.14 + index * 0.064 + seeded(index, 1) * 0.035,
    amplitude: 0.025 + seeded(index, 2) * 0.034,
    frequency: 1.25 + seeded(index, 3) * 1.65,
    phase: seeded(index, 4) * TAU,
    speed: 0.28 + seeded(index, 5) * 0.42,
    color: STRAND_COLORS[index % STRAND_COLORS.length],
    alpha: 0.055 + seeded(index, 6) * 0.07,
    width: 0.55 + seeded(index, 7) * 0.95,
    drift: -0.08 + seeded(index, 8) * 0.16,
  }))

const createParticles = (strandCount: number): Particle[] =>
  Array.from({ length: 58 }, (_, index) => ({
    strand: Math.floor(seeded(index, 11) * strandCount),
    offset: seeded(index, 12),
    speed: 0.018 + seeded(index, 13) * 0.05,
    size: 0.55 + seeded(index, 14) * 1.15,
    alpha: 0.12 + seeded(index, 15) * 0.28,
  }))

const clamp01 = (value: number) => Math.max(0, Math.min(1, value))

export default function DynamicSkillBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    const strands = createStrands()
    const particles = createParticles(strands.length)
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const mouse = {
      x: 0.62,
      y: 0.38,
      tx: 0.62,
      ty: 0.38,
      active: false,
      lastMove: 0,
    }

    let rafId = 0
    let reducedMotion = motionQuery.matches
    let pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5)
    let width = 0
    let height = 0

    const pointOnStrand = (strand: Strand, progress: number, time: number) => {
      const x = progress * width
      const primary = Math.sin(progress * strand.frequency * TAU + time * strand.speed + strand.phase)
      const secondary = Math.sin(progress * (strand.frequency * 0.37 + 0.85) * TAU - time * strand.speed * 1.42 + strand.phase * 0.6)
      const ribbon = Math.sin(progress * TAU * 0.55 + time * 0.22 + strand.phase)
      let y = height * (strand.base + strand.drift * 0.08) + primary * strand.amplitude * height
      y += secondary * strand.amplitude * height * 0.46
      y += ribbon * height * 0.01

      const mx = mouse.x * width
      const my = mouse.y * height
      const dx = x - mx
      const dy = y - my
      const radius = Math.max(width, height) * (mouse.active ? 0.2 : 0.11)
      const wake = Math.exp(-(dx * dx + dy * dy) / (radius * radius))
      const sway = Math.sin(time * 2.35 + strand.phase) * height * 0.03

      return {
        x: x + wake * (mouse.x - 0.5) * width * 0.025,
        y: y + wake * ((mouse.y - 0.5) * height * 0.055 + sway),
      }
    }

    const drawStrand = (strand: Strand, time: number, blur: boolean) => {
      ctx.beginPath()

      for (let step = 0; step <= 112; step += 1) {
        const progress = step / 112
        const point = pointOnStrand(strand, progress, time)

        if (step === 0) {
          ctx.moveTo(point.x, point.y)
        } else {
          ctx.lineTo(point.x, point.y)
        }
      }

      ctx.strokeStyle = `rgba(${strand.color}, ${blur ? strand.alpha * 0.28 : strand.alpha})`
      ctx.lineWidth = blur ? strand.width * 7 : strand.width
      ctx.stroke()
    }

    const draw = (now = 0, staticFrame = false) => {
      const time = staticFrame ? 18 : now * 0.00042

      mouse.x += (mouse.tx - mouse.x) * 0.055
      mouse.y += (mouse.ty - mouse.y) * 0.055
      if (now - mouse.lastMove > 1800) mouse.active = false

      ctx.clearRect(0, 0, width, height)
      ctx.globalCompositeOperation = 'source-over'
      ctx.filter = 'none'
      ctx.globalAlpha = 1

      const base = ctx.createLinearGradient(0, 0, width, height)
      base.addColorStop(0, 'rgba(0, 0, 0, 1)')
      base.addColorStop(0.5, 'rgba(5, 4, 3, 0.98)')
      base.addColorStop(1, 'rgba(0, 0, 0, 1)')
      ctx.fillStyle = base
      ctx.fillRect(0, 0, width, height)

      const lowField = ctx.createLinearGradient(width * 0.08, height * 0.18, width * 0.92, height * 0.86)
      lowField.addColorStop(0, 'rgba(255, 243, 234, 0.028)')
      lowField.addColorStop(0.46, 'rgba(228, 181, 146, 0.035)')
      lowField.addColorStop(0.72, 'rgba(238, 18, 18, 0.012)')
      lowField.addColorStop(1, 'rgba(218, 208, 200, 0.024)')
      ctx.fillStyle = lowField
      ctx.fillRect(0, 0, width, height)

      ctx.save()
      ctx.globalCompositeOperation = 'screen'
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.filter = 'blur(9px)'
      strands.forEach((strand) => drawStrand(strand, time, true))
      ctx.restore()

      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.filter = 'none'
      strands.forEach((strand) => drawStrand(strand, time, false))
      ctx.restore()

      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      particles.forEach((particle, index) => {
        const strand = strands[particle.strand]
        const progress = (particle.offset + time * particle.speed) % 1
        const point = pointOnStrand(strand, progress, time)
        const pulse = 0.55 + 0.45 * Math.sin(time * 4 + index)
        const radius = particle.size * (0.78 + pulse * 0.45)

        ctx.beginPath()
        ctx.fillStyle = `rgba(${strand.color}, ${particle.alpha * (0.7 + pulse * 0.3)})`
        ctx.arc(point.x, point.y, radius, 0, TAU)
        ctx.fill()

        if (index % 5 === 0) {
          const tail = pointOnStrand(strand, (progress - 0.018 + 1) % 1, time)
          ctx.beginPath()
          ctx.moveTo(tail.x, tail.y)
          ctx.lineTo(point.x, point.y)
          ctx.strokeStyle = `rgba(${strand.color}, ${particle.alpha * 0.34})`
          ctx.lineWidth = 0.8
          ctx.stroke()
        }
      })
      ctx.restore()

      if (mouse.active) {
        const x = mouse.x * width
        const y = mouse.y * height
        const radius = Math.max(width, height) * 0.16
        const wake = ctx.createRadialGradient(x, y, 0, x, y, radius)
        wake.addColorStop(0, 'rgba(228, 181, 146, 0.05)')
        wake.addColorStop(0.48, 'rgba(255, 243, 234, 0.02)')
        wake.addColorStop(1, 'rgba(228, 181, 146, 0)')
        ctx.fillStyle = wake
        ctx.fillRect(0, 0, width, height)
      }

      const scanY = (0.18 + ((time * 0.04) % 0.7)) * height
      ctx.beginPath()
      ctx.moveTo(0, scanY)
      ctx.lineTo(width, scanY + Math.sin(time * 0.8) * 10)
      ctx.strokeStyle = 'rgba(238, 18, 18, 0.08)'
      ctx.lineWidth = 1
      ctx.stroke()

      if (!reducedMotion && !staticFrame) {
        rafId = requestAnimationFrame(draw)
      }
    }

    const resize = () => {
      const bounds = canvas.parentElement?.getBoundingClientRect()
      const nextWidth = Math.max(1, Math.floor(bounds?.width || window.innerWidth))
      const nextHeight = Math.max(1, Math.floor(bounds?.height || window.innerHeight))
      pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5)
      width = nextWidth
      height = nextHeight
      canvas.width = Math.floor(nextWidth * pixelRatio)
      canvas.height = Math.floor(nextHeight * pixelRatio)
      canvas.style.width = `${nextWidth}px`
      canvas.style.height = `${nextHeight}px`
      ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
      draw(performance.now(), true)
    }

    const start = () => {
      cancelAnimationFrame(rafId)
      resize()
      if (!reducedMotion) {
        rafId = requestAnimationFrame(draw)
      }
    }

    const handlePointerMove = (event: PointerEvent) => {
      mouse.tx = clamp01(event.clientX / Math.max(1, window.innerWidth))
      mouse.ty = clamp01(event.clientY / Math.max(1, window.innerHeight))
      mouse.active = true
      mouse.lastMove = performance.now()
      if (reducedMotion) draw(performance.now(), true)
    }

    const handlePointerLeave = () => {
      mouse.active = false
    }

    const handleMotionChange = () => {
      reducedMotion = motionQuery.matches
      start()
    }

    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', handlePointerMove, { passive: true })
    window.addEventListener('pointerleave', handlePointerLeave)
    motionQuery.addEventListener('change', handleMotionChange)

    start()

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerleave', handlePointerLeave)
      motionQuery.removeEventListener('change', handleMotionChange)
    }
  }, [])

  return (
    <div className="dynamic-skill-bg" aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  )
}
