import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import type { Planet as PlanetType, Star } from '../types/graph'

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

  // Calculate planet position based on orbit
  const position = useMemo(() => {
    const angle = data.orbitPhase + data.orbitSpeed * time
    const x = star.position[0] + data.orbitRadius * Math.cos(angle)
    const y = star.position[1] + data.orbitRadius * Math.sin(angle) * Math.cos(data.orbitTilt)
    const z = star.position[2] + data.orbitRadius * Math.sin(angle) * Math.sin(data.orbitTilt)
    return [x, y, z] as [number, number, number]
  }, [data, star, time])

  // Create orbit path
  const orbitPoints = useMemo(() => {
    const points = []
    const segments = 64
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      const x = star.position[0] + data.orbitRadius * Math.cos(angle)
      const y = star.position[1] + data.orbitRadius * Math.sin(angle) * Math.cos(data.orbitTilt)
      const z = star.position[2] + data.orbitRadius * Math.sin(angle) * Math.sin(data.orbitTilt)
      points.push(new THREE.Vector3(x, y, z))
    }
    return points
  }, [data, star])

  const orbitGeometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints(orbitPoints)
    return geometry
  }, [orbitPoints])

  const planetColor = useMemo(() => new THREE.Color(data.color), [data.color])

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

      {/* Planet */}
      <group position={position}>
        {/* Glow */}
        <mesh>
          <sphereGeometry args={[data.size * 2, 16, 16]} />
          <meshBasicMaterial
            color={planetColor}
            transparent
            opacity={0.2}
            blending={THREE.AdditiveBlending}
          />
        </mesh>

        {/* Planet body */}
        <mesh ref={meshRef} onClick={onClick} scale={isSelected ? 1.3 : 1}>
          <sphereGeometry args={[data.size, 16, 16]} />
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
            position={[0, data.size + 0.38, 0]}
            center
            distanceFactor={7}
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
            position={[0, data.size + 0.68, 0]}
            center
            distanceFactor={7}
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
