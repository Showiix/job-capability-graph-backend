import { useRef, Suspense } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars as ThreeStars } from '@react-three/drei'
import { Star } from './Star'
import { Planet } from './Planet'
import type { Star as StarType, Planet as PlanetType, GraphData } from '../types/graph'

interface Scene3DProps {
  data: GraphData
  selectedStar: StarType | null
  selectedPlanet: PlanetType | null
  onStarClick: (star: StarType) => void
  onPlanetClick: (planet: PlanetType) => void
  showLabels: boolean
  filterTypes: string[]
  focusedJobId?: string
}

function Scene({ data, selectedStar, selectedPlanet, onStarClick, onPlanetClick, showLabels, filterTypes, focusedJobId }: Scene3DProps) {
  const timeRef = useRef(0)

  useFrame((_state, delta) => {
    timeRef.current += delta
  })

  const filteredPlanets = data.planets.filter((p) => filterTypes.includes(p.type))

  // Filter stars and planets based on focus
  const visibleStars = focusedJobId
    ? data.stars.filter(s => s.id === focusedJobId)
    : data.stars

  const visiblePlanets = focusedJobId
    ? filteredPlanets.filter(p => p.starId === focusedJobId)
    : filteredPlanets

  return (
    <>
      {/* Ambient light */}
      <ambientLight intensity={0.3} />

      {/* Point light at center */}
      <pointLight position={[0, 0, 0]} intensity={1} distance={50} decay={2} />

      {/* Background stars */}
      <ThreeStars radius={50} depth={50} count={2000} factor={3} saturation={0} fade speed={0.5} />

      {/* Render visible stars */}
      {visibleStars.map((star) => (
        <Star
          key={star.id}
          data={star}
          onClick={() => onStarClick(star)}
          isSelected={selectedStar?.id === star.id}
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
            showLabels={showLabels}
          />
        )
      })}

      {/* Camera controls */}
      <OrbitControls
        enablePan
        enableZoom
        enableRotate
        minDistance={focusedJobId ? 3 : 5}
        maxDistance={focusedJobId ? 25 : 40}
        autoRotate={!selectedStar && !selectedPlanet}
        autoRotateSpeed={focusedJobId ? 0.5 : 0.3}
      />
    </>
  )
}

export function GraphScene3D(props: Scene3DProps) {
  return (
    <Canvas
      camera={{ position: [0, 10, 20], fov: 60 }}
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
