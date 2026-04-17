import { useState, useEffect } from 'react'

interface TourStep {
  target: string
  title: string
  content: string
  position: 'top' | 'bottom' | 'left' | 'right'
}

const TOUR_STEPS: TourStep[] = [
  {
    target: '[data-tour="kpi-strip"]',
    title: 'KPI Dashboard',
    content: 'Real-time key performance indicators: active policies, total premiums, loss ratio, and pending claims.',
    position: 'bottom',
  },
  {
    target: '[data-tour="zone-map"]',
    title: 'Zone Risk Map',
    content: 'Interactive map showing all 10 Bengaluru zones. Colors indicate risk tiers. Click a zone to see details.',
    position: 'bottom',
  },
  {
    target: '[data-tour="signal-panel"]',
    title: 'QuadSignal Engine',
    content: '4 independent signals (Environmental, Mobility, Economic, Crowd) must converge to trigger a claim. Watch them update in real-time.',
    position: 'left',
  },
  {
    target: '[data-tour="simulator"]',
    title: 'Disruption Simulator',
    content: 'Trigger scenarios like flash floods, severe AQI, or transport strikes. Watch the full pipeline: signals → fusion → claims → payouts.',
    position: 'left',
  },
  {
    target: '[data-tour="claims-queue"]',
    title: 'Claims Queue',
    content: 'Review pending claims with AI-powered audit reports. Approve or reject with full exclusion and fraud analysis.',
    position: 'top',
  },
  {
    target: '[data-tour="analytics"]',
    title: 'Analytics Dashboard',
    content: 'Claims by zone, daily payouts, and loss ratio tracking. All powered by real data from the backend.',
    position: 'top',
  },
]

export default function DemoTour() {
  const [active, setActive] = useState(false)
  const [step, setStep] = useState(0)
  const [position, setPosition] = useState({ top: 0, left: 0 })

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('demo') === 'true') {
      setTimeout(() => setActive(true), 0);
    }
  }, [])

  useEffect(() => {
    if (!active) return
    const el = document.querySelector(TOUR_STEPS[step]?.target)
    if (el) {
      const rect = el.getBoundingClientRect()
      const tourStep = TOUR_STEPS[step]
      let top = 0, left = 0

      switch (tourStep.position) {
        case 'bottom':
          top = rect.bottom + 12
          left = rect.left + rect.width / 2
          break
        case 'top':
          top = rect.top - 12
          left = rect.left + rect.width / 2
          break
        case 'left':
          top = rect.top + rect.height / 2
          left = rect.left - 12
          break
        case 'right':
          top = rect.top + rect.height / 2
          left = rect.right + 12
          break
      }

      setTimeout(() => setPosition({ top, left }), 0);
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [active, step])

  if (!active) return null

  const currentStep = TOUR_STEPS[step]
  const isLast = step === TOUR_STEPS.length - 1

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/40 z-[998]" onClick={() => setActive(false)} />

      {/* Tour card */}
      <div
        className="fixed z-[999] bg-slate-800 border border-blue-500/50 rounded-xl p-4 shadow-2xl shadow-blue-500/20 max-w-sm"
        style={{
          top: `${Math.min(position.top, window.innerHeight - 200)}px`,
          left: `${Math.min(Math.max(position.left - 160, 16), window.innerWidth - 340)}px`,
        }}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-blue-400 text-xs font-bold uppercase tracking-wider">
            Step {step + 1} of {TOUR_STEPS.length}
          </span>
          <button
            onClick={() => setActive(false)}
            className="text-slate-500 hover:text-white text-xs"
          >
            Skip Tour
          </button>
        </div>

        <h4 className="text-white font-bold text-sm mb-1">{currentStep.title}</h4>
        <p className="text-slate-300 text-xs leading-relaxed mb-3">{currentStep.content}</p>

        <div className="flex items-center justify-between">
          <div className="flex gap-1">
            {TOUR_STEPS.map((_, i) => (
              <div
                key={i}
                className={`w-1.5 h-1.5 rounded-full ${i === step ? 'bg-blue-400' : 'bg-slate-600'}`}
              />
            ))}
          </div>

          <div className="flex gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep(step - 1)}
                className="px-3 py-1 text-xs text-slate-400 hover:text-white transition-colors"
              >
                Back
              </button>
            )}
            <button
              onClick={() => isLast ? setActive(false) : setStep(step + 1)}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded-lg transition-colors"
            >
              {isLast ? 'Finish' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
