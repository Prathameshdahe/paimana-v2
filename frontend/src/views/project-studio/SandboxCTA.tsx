import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'

interface SandboxCTAProps {
  projectId: string
  projectName: string
}

export function SandboxCTA({ projectId, projectName }: SandboxCTAProps) {
  const navigate = useNavigate()

  return (
    <div className="flex flex-col gap-5 text-center">
      <div className="font-sans">
        <div className="text-sm font-semibold text-fg-muted uppercase tracking-wider mb-2">Prescriptive Sandbox</div>
        <div className="text-base text-fg-base font-medium leading-relaxed">
          Simulate interventions for {projectName}
        </div>
      </div>
      <Button
        variant="primary"
        size="sm"
        className="w-fit self-center text-xs font-semibold px-6"
        onClick={() => navigate(`/sandbox?project=${projectId}`)}
      >
        OPEN IN SANDBOX →
      </Button>
    </div>
  )
}
