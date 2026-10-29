import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { EdgesGeometry, IcosahedronGeometry } from 'three'
import { Hexagon } from 'lucide-react'

function FacetedVolume({ rotation, paused }) {
  const group = useRef()
  const time = useRef(0)
  const geometry = useMemo(() => new IcosahedronGeometry(1.65, 1), [])
  const edges = useMemo(() => new EdgesGeometry(geometry, 1), [geometry])
  const points = useMemo(() => {
    const positions = geometry.attributes.position
    const seen = new Set()
    const result = []
    for (let i = 0; i < positions.count; i++) {
      const point = [positions.getX(i), positions.getY(i), positions.getZ(i)]
      const key = point.map((value) => value.toFixed(4)).join(',')
      if (!seen.has(key)) { seen.add(key); result.push(point) }
    }
    return result
  }, [geometry])
  useFrame(({ pointer }, delta) => {
    if (!group.current) return
    if (!paused) time.current += delta * 0.065
    const target = rotation + time.current + (paused ? 0 : pointer.x * 0.18)
    group.current.rotation.y = paused ? target : group.current.rotation.y + (target - group.current.rotation.y) * 0.055
    group.current.rotation.x = paused ? 0.16 : group.current.rotation.x + (0.16 - pointer.y * 0.08 - group.current.rotation.x) * 0.055
  })
  return <group ref={group} rotation={[0.16, rotation, -0.04]}>
    <mesh geometry={geometry}><meshStandardMaterial color="#bdc3c1" metalness={0.42} roughness={0.43} flatShading polygonOffset polygonOffsetFactor={1} polygonOffsetUnits={1} /></mesh>
    <lineSegments geometry={edges}><lineBasicMaterial color="#121919" /></lineSegments>
    {points.map((point, index) => <mesh key={index} position={point}><icosahedronGeometry args={[0.047, 1]} /><meshStandardMaterial color="#4d5857" metalness={0.75} roughness={0.24} /></mesh>)}
  </group>
}

export default function CloudScene({ rotation, paused }) {
  const container = useRef()
  const [active, setActive] = useState(true)
  useEffect(() => {
    let inView = true
    const update = () => setActive(inView && !document.hidden)
    const observer = new IntersectionObserver(([entry]) => { inView = entry.isIntersecting; update() })
    observer.observe(container.current)
    document.addEventListener('visibilitychange', update)
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', update) }
  }, [])
  return <div ref={container} style={{ width: '100%', height: '100%' }}><Canvas
    frameloop={paused || !active ? 'demand' : 'always'} dpr={[1, 1.5]}
    camera={{ position: [0, 0.1, 5.6], fov: 40 }}
    gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
    fallback={<div className="static-cloud"><Hexagon size={160} strokeWidth={0.7} aria-hidden="true" /></div>}
    aria-hidden="true"
  >
    <ambientLight intensity={0.65} />
    <directionalLight position={[1.5, 4, 4]} intensity={3.4} color="#eff4f4" />
    <directionalLight position={[-4, 0, -1]} intensity={0.6} color="#9dafb1" />
    <FacetedVolume rotation={rotation} paused={paused || !active} />
  </Canvas></div>
}
