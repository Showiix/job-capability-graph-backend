import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import type { Star as StarType } from '../types/graph'

interface StarProps {
  data: StarType
  onClick: () => void
  isSelected: boolean
  showLabel?: boolean
}

export function Star({ data, onClick, isSelected, showLabel = true }: StarProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const glowRef = useRef<THREE.Mesh>(null)
  const visualSize = useMemo(() => Math.max(0.42, data.size * 0.64), [data.size])

  // Pulsing animation for selected star
  useFrame((state) => {
    if (meshRef.current && isSelected) {
      const scale = 1 + Math.sin(state.clock.elapsedTime * 2) * 0.1
      meshRef.current.scale.setScalar(scale)
    } else if (meshRef.current) {
      meshRef.current.scale.setScalar(1)
    }

    if (glowRef.current) {
      glowRef.current.rotation.z += 0.005
    }
  })

  const starColor = useMemo(() => new THREE.Color(data.color), [data.color])

  return (
    <group position={data.position}>
      {/* Outer glow */}
      <mesh ref={glowRef}>
        <sphereGeometry args={[visualSize * 2.15, 32, 32]} />
        <meshBasicMaterial
          color={starColor}
          transparent
          opacity={isSelected ? 0.26 : 0.17}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* Main star body */}
      <mesh ref={meshRef} onClick={onClick}>
        <sphereGeometry args={[visualSize, 32, 32]} />
        <meshStandardMaterial
          color={starColor}
          emissive={starColor}
          emissiveIntensity={1.15}
          roughness={0.2}
          metalness={0.3}
        />
      </mesh>

      {/* Label */}
      {showLabel && (
        <Html
          position={[0, visualSize + 0.72, 0]}
          center
          style={{ pointerEvents: 'none' }}
        >
          <div
            className={`graph-node-label graph-node-label--star${isSelected ? ' is-selected' : ''}`}
            style={{
              color: isSelected ? '#ffffff' : '#fff3ea',
              textShadow: `0 0 12px ${data.color}, 0 2px 10px rgba(0,0,0,0.88)`,
            }}
          >
            {data.label}
          </div>
        </Html>
      )}

      {/* Lens flare effect */}
      {[0, Math.PI / 2, Math.PI, (Math.PI * 3) / 2].map((angle, i) => (
        <mesh
          key={i}
          position={[
            Math.cos(angle) * visualSize * 1.5,
            Math.sin(angle) * visualSize * 1.5,
            0,
          ]}
        >
          <planeGeometry args={[visualSize * 2, 0.05]} />
          <meshBasicMaterial
            color={starColor}
            transparent
            opacity={0.3}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      ))}
    </group>
  )
}
