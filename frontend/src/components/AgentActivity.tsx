'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronRight, Bot, Cpu, Brain, Sparkles, AlertTriangle } from 'lucide-react';
import { cn, formatDuration, formatCost } from '@/lib/utils';

interface AgentEvent {
  timestamp: string;
  event_type: string;
  agent_name: string;
  stage: number;
  data: {
    stage_name?: string;
    status?: string;
    detail?: string;
    cost?: number;
    error?: string;
    traceback?: string;
  };
}

interface AgentActivityProps {
  events: AgentEvent[];
  className?: string;
}

const agentIcons: Record<string, typeof Bot> = {
  'DataOrchestrator': Cpu,
  'DiscoveryAgent': Sparkles,
  'ExternalDiscoveryAgent': Sparkles,
  'VerticalAnalystAgent': Brain,
  'SynthesizerAgent': Brain,
  'JudgeAgent': Bot,
  'Pipeline': Bot,
  'Claude Opus': Brain,
  'GPT-5.2': Cpu,
  'Gemini Deep Research': Sparkles,
};

const stageColors: Record<number, string> = {
  1: 'border-l-blue-500',
  2: 'border-l-purple-500',
  3: 'border-l-amber-500',
  4: 'border-l-green-500',
  5: 'border-l-cyan-500',
  6: 'border-l-pink-500',
};

export function AgentActivity({ events, className }: AgentActivityProps) {
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpanded = (idx: number) => {
    const next = new Set(expandedIds);
    if (next.has(idx)) {
      next.delete(idx);
    } else {
      next.add(idx);
    }
    setExpandedIds(next);
  };

  // Group events by stage
  const recentEvents = events.slice(-50).reverse();

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="kp-panel-header flex items-center justify-between">
        <h3 className="kp-display-sm">Agent Activity</h3>
        <span className="kp-label">{events.length} events</span>
      </div>

      {/* Event list */}
      <div className="flex-1 overflow-y-auto">
        {recentEvents.length === 0 && (
          <div className="text-center py-8 text-[var(--kp-text-muted)]">
            No activity yet
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {recentEvents.map((event, idx) => {
            const Icon = agentIcons[event.agent_name] || Bot;
            const isExpanded = expandedIds.has(idx);
            const isError = event.event_type.includes('error');
            const hasDetail = event.data.detail || event.data.error || event.data.traceback;

            return (
              <motion.div
                key={`${event.timestamp}-${idx}`}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                className={cn(
                  'border-l-2 border-b border-b-[var(--kp-border)]',
                  stageColors[event.stage] || 'border-l-[var(--kp-border)]',
                  isError && 'border-l-[var(--kp-red)] bg-red-950/20'
                )}
              >
                <button
                  onClick={() => hasDetail && toggleExpanded(idx)}
                  className={cn(
                    'w-full text-left p-3 flex items-start gap-3',
                    hasDetail && 'cursor-pointer hover:bg-[var(--kp-elevated)]'
                  )}
                  disabled={!hasDetail}
                >
                  {/* Icon */}
                  <div className={cn(
                    'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
                    'bg-[var(--kp-elevated)]',
                    isError && 'bg-red-950'
                  )}>
                    {isError ? (
                      <AlertTriangle className="w-4 h-4 text-[var(--kp-red)]" />
                    ) : (
                      <Icon className="w-4 h-4 text-[var(--kp-text-muted)]" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        'font-medium text-sm',
                        isError && 'text-[var(--kp-red)]'
                      )}>
                        {event.agent_name}
                      </span>
                      <span className="kp-label text-[0.65rem]">
                        Stage {event.stage}
                      </span>
                    </div>

                    <div className="text-sm text-[var(--kp-text-muted)] mt-0.5">
                      {event.data.stage_name && (
                        <span>{event.data.stage_name} - </span>
                      )}
                      <span className={cn(
                        event.data.status === 'complete' && 'text-[var(--kp-green)]',
                        event.data.status === 'error' && 'text-[var(--kp-red)]'
                      )}>
                        {event.data.status || event.event_type}
                      </span>
                    </div>

                    {event.data.cost !== undefined && (
                      <div className="text-xs text-[var(--kp-text-muted)] mt-1">
                        Cost: {formatCost(event.data.cost)}
                      </div>
                    )}
                  </div>

                  {/* Expand icon */}
                  {hasDetail && (
                    <div className="flex-shrink-0 text-[var(--kp-text-muted)]">
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4" />
                      ) : (
                        <ChevronRight className="w-4 h-4" />
                      )}
                    </div>
                  )}
                </button>

                {/* Expanded detail */}
                <AnimatePresence>
                  {isExpanded && hasDetail && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="px-3 pb-3 pl-14">
                        {event.data.detail && (
                          <p className="text-sm text-[var(--kp-text-secondary)] whitespace-pre-wrap">
                            {event.data.detail}
                          </p>
                        )}
                        {event.data.error && (
                          <p className="text-sm text-[var(--kp-red)] mt-2">
                            Error: {event.data.error}
                          </p>
                        )}
                        {event.data.traceback && (
                          <pre className="text-xs text-[var(--kp-text-muted)] mt-2 p-2 bg-[var(--kp-abyss)] rounded overflow-x-auto">
                            {event.data.traceback}
                          </pre>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
