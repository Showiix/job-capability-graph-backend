interface FrameCornersProps {
  className?: string
}

export function FrameCorners({ className = '' }: FrameCornersProps) {
  return (
    <div className={`frame-corners ${className}`.trim()} aria-hidden="true">
      <span className="frame-corner top-left" />
      <span className="frame-corner top-right" />
      <span className="frame-corner bottom-left" />
      <span className="frame-corner bottom-right" />
    </div>
  )
}
