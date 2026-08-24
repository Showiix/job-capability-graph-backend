import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import type { Planet as PlanetType, Star } from '../types/graph'

export const PLANET_ORBIT_VISUAL_SCALE = 0.62

interface PlanetProps {
  data: PlanetType
  star: Star
  time: number
  onClick: () => void
  isSelected: boolean
  showLabels: boolean
}

export function Planet({ data, star, time, onClick, isSelected, showLabels }: PlanetProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  // const orbitRef = useRef<THREE.Line>(null)
  const visualOrbitRadius = data.orbitRadius * PLANET_ORBIT_VISUAL_SCALE
  const visualSize = Math.max(0.1, data.size * 0.76)

  // Calculate planet position based on orbit
  const position = useMemo(() => {
    const angle = data.orbitPhase + data.orbitSpeed * time
    const x = star.position[0] + visualOrbitRadius * Math.cos(angle)
    const y = star.position[1] + visualOrbitRadius * Math.sin(angle) * Math.cos(data.orbitTilt)
    const z = star.position[2] + visualOrbitRadius * Math.sin(angle) * Math.sin(data.orbitTilt)
    return [x, y, z] as [number, number, number]
  }, [data, star, time, visualOrbitRadius])

  // Create orbit path
  const orbitPoints = useMemo(() => {
    const points = []
    const segments = 64
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      const x = star.position[0] + visualOrbitRadius * Math.cos(angle)
      const y = star.position[1] + visualOrbitRadius * Math.sin(angle) * Math.cos(data.orbitTilt)
      const z = star.position[2] + visualOrbitRadius * Math.sin(angle) * Math.sin(data.orbitTilt)
      points.push(new THREE.Vector3(x, y, z))
    }
    return points
  }, [data, star, visualOrbitRadius])

  const orbitGeometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints(orbitPoints)
    return geometry
  }, [orbitPoints])

  const connectionGeometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...star.position),
      new THREE.Vector3(...position),
    ])
    return geometry
  }, [position, star.position])

  const planetColor = useMemo(() => new THREE.Color(data.color), [data.color])
  const connectionColor = data.isRequired ? data.color : '#dad0c8'
  const connectionOpacity = isSelected ? 0.76 : data.isRequired ? 0.42 : 0.28

  useFrame(() => {
    if (meshRef.current && isSelected) {
      meshRef.current.rotation.y += 0.02
    }
  })

  return (
    <>
      {/* Orbit ring */}
      <primitive object={new THREE.Line(orbitGeometry, new THREE.LineBasicMaterial({
        color: data.isRequired ? star.color : '#a49b92',
        transparent: true,
        opacity: data.isRequired ? 0.15 : 0.08,
      }))} />

      {/* Skill relation line */}
      <primitive object={new THREE.Line(connectionGeometry, new THREE.LineBasicMaterial({
        color: connectionColor,
        transparent: true,
        opacity: connectionOpacity,
        depthWrite: false,
      }))} />

      {/* Planet */}
      <group position={position}>
        {/* Glow */}
        <mesh>
          <sphereGeometry args={[visualSize * 2, 16, 16]} />
          <meshBasicMaterial
            color={planetColor}
            transparent
            opacity={0.2}
            blending={THREE.AdditiveBlending}
          />
        </mesh>

        {/* Planet body */}
        <mesh ref={meshRef} onClick={onClick} scale={isSelected ? 1.3 : 1}>
          <sphereGeometry args={[visualSize, 16, 16]} />
          <meshStandardMaterial
            color={planetColor}
            emissive={planetColor}
            emissiveIntensity={0.5}
            roughness={0.6}
            metalness={0.2}
          />
        </mesh>

        {/* Label */}
        {(showLabels || isSelected) && (
          <Html
            position={[0, visualSize + 0.34, 0]}
            center
            style={{ pointerEvents: 'none' }}
          >
            <div
              className={`graph-node-label graph-node-label--planet${isSelected ? ' is-selected' : ''}`}
              style={{
                color: isSelected ? data.color : '#dad0c8',
                textShadow: `0 0 10px ${data.color}, 0 2px 8px rgba(0,0,0,0.9)`,
              }}
            >
              {data.label}
            </div>
          </Html>
        )}

        {/* Confidence badge for selected */}
        {isSelected && (
          <Html
            position={[0, visualSize + 0.64, 0]}
            center
            style={{ pointerEvents: 'none' }}
          >
            <div className="graph-node-label graph-node-label--confidence">
              {Math.round(data.confidence)}%
            </div>
          </Html>
        )}
      </group>
    </>
  )
}
