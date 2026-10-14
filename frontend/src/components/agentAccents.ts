export interface AgentAccent {
  ring: string
  text: string
  dot: string
  bar: string
}

export const AGENT_ACCENTS: Record<string, AgentAccent> = {
  economist: {
    ring: 'ring-amber-500/30',
    text: 'text-amber-300',
    dot: 'bg-amber-400',
    bar: 'from-amber-400 to-amber-600',
  },
  lawyer: {
    ring: 'ring-sky-500/30',
    text: 'text-sky-300',
    dot: 'bg-sky-400',
    bar: 'from-sky-400 to-sky-600',
  },
  doctor: {
    ring: 'ring-rose-500/30',
    text: 'text-rose-300',
    dot: 'bg-rose-400',
    bar: 'from-rose-400 to-rose-600',
  },
  scientist: {
    ring: 'ring-emerald-500/30',
    text: 'text-emerald-300',
    dot: 'bg-emerald-400',
    bar: 'from-emerald-400 to-emerald-600',
  },
  ethicist: {
    ring: 'ring-violet-500/30',
    text: 'text-violet-300',
    dot: 'bg-violet-400',
    bar: 'from-violet-400 to-violet-600',
  },
  analyst: {
    ring: 'ring-cyan-500/30',
    text: 'text-cyan-300',
    dot: 'bg-cyan-400',
    bar: 'from-cyan-400 to-cyan-600',
  },
}

export const FALLBACK_ACCENT: AgentAccent = {
  ring: 'ring-indigo-500/30',
  text: 'text-indigo-300',
  dot: 'bg-indigo-400',
  bar: 'from-indigo-400 to-indigo-600',
}

export function accentFor(agent: string): AgentAccent {
  return AGENT_ACCENTS[agent] ?? FALLBACK_ACCENT
}
