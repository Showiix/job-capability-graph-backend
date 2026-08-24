import { useEffect, useLayoutEffect, useMemo, useRef, useState, Suspense } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stars as ThreeStars } from '@react-three/drei'
import { Star } from './Star'
import { Planet, PLANET_ORBIT_VISUAL_SCALE } from './Planet'
import type { Star as StarType, Planet as PlanetType, GraphData } from '../types/graph'

interface Scene3DProps {
  data: GraphData
  selectedStar: StarType | null
  selectedPlanet: PlanetType | null
  onStarClick: (star: StarType) => void
  onPlanetClick: (planet: PlanetType) => void
  showJobLabels: boolean
  showSkillLabels: boolean
  filterTypes: string[]
}

type SceneView = {
  center: [number, number, number]
  radius: number
  distance: number
}

const DEFAULT_SCENE_VIEW: SceneView = {
  center: [0, 0, 0],
  radius: 16,
  distance: 32,
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function calculateSceneView(data: GraphData): SceneView {
  if (data.stars.length === 0) return DEFAULT_SCENE_VIEW

  const orbitByStar = new Map<string, number>()
  data.planets.forEach((planet) => {
    const visualOrbit = planet.orbitRadius * PLANET_ORBIT_VISUAL_SCALE
    orbitByStar.set(planet.starId, Math.max(orbitByStar.get(planet.starId) ?? 0, visualOrbit))
  })

  const min: [number, number, number] = [Infinity, Infinity, Infinity]
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity]

  data.stars.forEach((star) => {
    const padding = Math.max(1.8, (orbitByStar.get(star.id) ?? 1.2) + star.size * 1.45)
    for (let index = 0; index < 3; index += 1) {
      min[index] = Math.min(min[index], star.position[index] - padding)
      max[index] = Math.max(max[index], star.position[index] + padding)
    }
  })

  const center: [number, number, number] = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ]
  const radius = Math.max(
    10,
    Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2,
  )
  const distance = clamp(radius * 1.42, 30, 76)

  return { center, radius, distance }
}

function Scene({
  data,
  selectedStar,
  selectedPlanet,
  onStarClick,
  onPlanetClick,
  showJobLabels,
  showSkillLabels,
  filterTypes,
}: Scene3DProps) {
  const timeRef = useRef(0)
  const controlsRef = useRef<any>(null)
  const { camera } = useThree()
  const sceneView = useMemo(() => calculateSceneView(data), [data])

  useLayoutEffect(() => {
    const [centerX, centerY, centerZ] = sceneView.center
    camera.position.set(
      centerX,
      centerY + clamp(sceneView.radius * 0.22, 4, 12),
      centerZ + sceneView.distance,
    )
    camera.near = 0.1
    camera.far = Math.max(220, sceneView.distance * 5)
    camera.lookAt(centerX, centerY, centerZ)
    camera.updateProjectionMatrix()

    if (controlsRef.current) {
      controlsRef.current.target.set(centerX, centerY, centerZ)
      controlsRef.current.update()
    }
  }, [camera, sceneView])

  useFrame((_state, delta) => {
    timeRef.current += delta
  })

  const filteredPlanets = data.planets.filter((p) => filterTypes.includes(p.type))

  const visibleStars = data.stars
  const visiblePlanets = filteredPlanets

  return (
    <>
      {/* Ambient light */}
      <ambientLight intensity={0.3} />

      {/* Point light at center */}
      <pointLight position={sceneView.center} intensity={1.35} distance={sceneView.distance * 2.2} decay={2} />

      {/* Background stars */}
      <ThreeStars radius={50} depth={50} count={2000} factor={3} saturation={0} fade speed={0.5} />

      {/* Render visible stars */}
      {visibleStars.map((star) => (
        <Star
          key={star.id}
          data={star}
          onClick={() => onStarClick(star)}
          isSelected={selectedStar?.id === star.id}
          showLabel={showJobLabels}
        />
      ))}

      {/* Render visible planets */}
      {visiblePlanets.map((planet) => {
        const star = data.stars.find((s) => s.id === planet.starId)
        if (!star) return null
        return (
          <Planet
            key={planet.id}
            data={planet}
            star={star}
            time={timeRef.current}
            onClick={() => onPlanetClick(planet)}
            isSelected={selectedPlanet?.id === planet.id}
            showLabels={showSkillLabels}
          />
        )
      })}

      {/* Camera controls */}
      <OrbitControls
        ref={controlsRef}
        makeDefault
        enablePan
        enableZoom
        enableRotate
        enableDamping
        dampingFactor={0.08}
        target={sceneView.center}
        minDistance={Math.max(5, sceneView.radius * 0.24)}
        maxDistance={Math.max(92, sceneView.distance * 1.9)}
        autoRotate={!selectedStar && !selectedPlanet}
        autoRotateSpeed={0.24}
      />
    </>
  )
}

export function GraphScene3D(props: Scene3DProps) {
  const [webglReady, setWebglReady] = useState<boolean | null>(null)

  useEffect(() => {
    try {
      const testCanvas = document.createElement('canvas')
      const gl =
        testCanvas.getContext('webgl2') ||
        testCanvas.getContext('webgl') ||
        testCanvas.getContext('experimental-webgl')

      if (gl && 'getExtension' in gl) {
        gl.getExtension('WEBGL_lose_context')?.loseContext()
      }

      setWebglReady(Boolean(gl))
    } catch {
      setWebglReady(false)
    }
  }, [])

  if (webglReady !== true) {
    return (
      <div className="graph-webgl-fallback">
        <div className="loading-reticle" />
        <strong>{webglReady === false ? '3D 渲染通道不可用' : '正在初始化 3D 图谱'}</strong>
        <span>
          {webglReady === false
            ? '当前浏览器没有可用 WebGL，上方筛选和右侧详情仍可使用。请启用硬件加速后刷新。'
            : '正在检测浏览器 WebGL 能力。'}
        </span>
      </div>
    )
  }

  return (
    <Canvas
      camera={{ position: [0, 10, 38], fov: 54 }}
      dpr={[1, 1.5]}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      onCreated={({ gl }) => {
        gl.setClearColor('#000000', 1)
      }}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        background: '#000000',
      }}
    >
      <Suspense fallback={null}>
        <Scene {...props} />
      </Suspense>
    </Canvas>
  )
}
