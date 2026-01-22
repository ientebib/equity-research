'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { Check, Loader2, AlertCircle, Circle } from 'lucide-react';
import { cn, formatDuration } from '@/lib/utils';
import type { Stage, StageStatus } from '@/types';

interface PipelineStagesProps {
  stages: Stage[];
  className?: string;
}

const statusIcons: Record<StageStatus, React.ReactNode> = {
  pending: <Circle className="w-4 h-4" />,
  running: <Loader2 className="w-4 h-4 animate-spin" />,
  complete: <Check className="w-4 h-4" />,
  error: <AlertCircle className="w-4 h-4" />,
};

const statusColors: Record<StageStatus, string> = {
  pending: 'text-[var(--kp-text-muted)] border-[var(--kp-border)]',
  running: 'text-[var(--kp-green)] border-[var(--kp-green)]',
  complete: 'text-[var(--kp-text)] border-[var(--kp-text-muted)]',
  error: 'text-[var(--kp-red)] border-[var(--kp-red)]',
};

export function PipelineStages({ stages, className }: PipelineStagesProps) {
  return (
    <div className={cn('space-y-1', className)}>
      {stages.map((stage, idx) => (
        <motion.div
          key={stage.id}
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: idx * 0.05 }}
          className={cn(
            'flex items-center gap-4 px-4 py-3 rounded-lg transition-all',
            stage.status === 'running' && 'bg-[var(--kp-elevated)]',
            stage.status === 'complete' && 'opacity-70'
          )}
        >
          {/* Stage number and status icon */}
          <div
            className={cn(
              'flex items-center justify-center w-8 h-8 rounded-full border-2 transition-colors',
              statusColors[stage.status]
            )}
          >
            {statusIcons[stage.status]}
          </div>

          {/* Stage info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="kp-label">{stage.shortName}</span>
              <span className={cn(
                'font-medium transition-colors',
                stage.status === 'running' && 'text-[var(--kp-green)]',
                stage.status === 'pending' && 'text-[var(--kp-text-muted)]'
              )}>
                {stage.name}
              </span>
            </div>

            {/* Detail text */}
            <AnimatePresence mode="wait">
              {stage.detail && (
                <motion.p
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="text-sm text-[var(--kp-text-muted)] mt-1 truncate"
                >
                  {stage.detail}
                </motion.p>
              )}
            </AnimatePresence>
          </div>

          {/* Duration */}
          {stage.duration !== undefined && (
            <span className="kp-mono text-sm text-[var(--kp-text-muted)]">
              {formatDuration(stage.duration)}
            </span>
          )}

          {/* Running indicator bar */}
          {stage.status === 'running' && (
            <motion.div
              className="absolute left-0 top-0 bottom-0 w-1 bg-[var(--kp-green)] rounded-r"
              layoutId="activeStage"
            />
          )}
        </motion.div>
      ))}
    </div>
  );
}

// Compact horizontal version for header
export function PipelineProgress({ stages, className }: { stages: Stage[]; className?: string }) {
  const completedCount = stages.filter(s => s.status === 'complete').length;
  const progress = (completedCount / stages.length) * 100;

  return (
    <div className={cn('space-y-2', className)}>
      {/* Progress bar */}
      <div className="h-1.5 bg-[var(--kp-border)] rounded-full overflow-hidden">
        <motion.div
          className="h-full bg-gradient-to-r from-[var(--kp-green)] to-[var(--kp-cyan)] rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>

      {/* Stage dots */}
      <div className="flex justify-between">
        {stages.map((stage) => (
          <div
            key={stage.id}
            className="flex flex-col items-center gap-1"
          >
            <div
              className={cn(
                'w-2 h-2 rounded-full transition-all',
                stage.status === 'pending' && 'bg-[var(--kp-border)]',
                stage.status === 'running' && 'bg-[var(--kp-green)] animate-pulse-soft',
                stage.status === 'complete' && 'bg-[var(--kp-text-muted)]',
                stage.status === 'error' && 'bg-[var(--kp-red)]'
              )}
            />
            <span className="kp-label text-[0.6rem]">{stage.shortName}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
