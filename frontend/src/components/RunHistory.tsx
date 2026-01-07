'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Clock, DollarSign, TrendingUp, TrendingDown, Minus, Loader2, AlertCircle } from 'lucide-react';
import { cn, formatDuration, formatCost, formatDate } from '@/lib/utils';
import api from '@/lib/api';

interface Run {
  run_id: string;
  ticker: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  duration?: number;
  total_cost?: number;
  current_stage?: number;
  current_agent?: string;
  cost?: number;
  verdict?: {
    investment_view: string;
    conviction: string;
    confidence: number;
  };
}

interface RunHistoryProps {
  onSelectRun: (runId: string) => void;
  onNewRun: () => void;
  selectedRunId?: string | null;
  activeRunId?: string | null;
  className?: string;
}

const verdictIcons = {
  BUY: TrendingUp,
  SELL: TrendingDown,
  HOLD: Minus,
};

const verdictColors = {
  BUY: 'text-[var(--kp-green)]',
  SELL: 'text-[var(--kp-red)]',
  HOLD: 'text-[var(--kp-amber)]',
};

export function RunHistory({ onSelectRun, onNewRun, selectedRunId, activeRunId, className }: RunHistoryProps) {
  const [runs, setRuns] = useState<{ completed: Run[]; active: Run[] }>({ completed: [], active: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch runs on mount and periodically
  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const data = await api.listRuns();
        setRuns(data);
        setError(null);
      } catch (e) {
        setError('Failed to load runs');
        console.error(e);
      } finally {
        setLoading(false);
      }
    };

    fetchRuns();
    const interval = setInterval(fetchRuns, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, []);

  const allRuns = [...runs.active, ...runs.completed];

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="p-4 border-b border-[var(--kp-border)]">
        <button
          onClick={onNewRun}
          className="kp-btn kp-btn-primary w-full flex items-center justify-center gap-2"
        >
          <Plus className="w-4 h-4" />
          New Analysis
        </button>
      </div>

      {/* Run list */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-[var(--kp-text-muted)]" />
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-[var(--kp-red)] text-sm p-4">
            <AlertCircle className="w-4 h-4" />
            {error}
          </div>
        )}

        {!loading && !error && allRuns.length === 0 && (
          <div className="text-center py-8 text-[var(--kp-text-muted)]">
            <p>No research runs yet</p>
            <p className="text-sm mt-1">Start your first analysis above</p>
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {allRuns.map((run, idx) => {
            const isActive = run.status === 'running' || run.status === 'pending';
            const isSelected = run.run_id === selectedRunId;
            const VerdictIcon = run.verdict?.investment_view
              ? verdictIcons[run.verdict.investment_view as keyof typeof verdictIcons]
              : null;

            return (
              <motion.button
                key={run.run_id}
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 10 }}
                transition={{ delay: idx * 0.03 }}
                onClick={() => onSelectRun(run.run_id)}
                className={cn(
                  'w-full text-left p-4 border-b border-[var(--kp-border)] transition-colors',
                  'hover:bg-[var(--kp-elevated)]',
                  isSelected && 'bg-[var(--kp-elevated)] border-l-2 border-l-[var(--kp-green)]',
                  isActive && 'bg-[var(--kp-surface)]'
                )}
              >
                {/* Ticker and status */}
                <div className="flex items-center justify-between mb-2">
                  <span className="kp-ticker text-sm">{run.ticker}</span>

                  {isActive ? (
                    <span className="flex items-center gap-1.5 text-xs text-[var(--kp-green)]">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--kp-green)] animate-pulse-soft" />
                      Stage {run.current_stage || 1}
                    </span>
                  ) : run.verdict ? (
                    <span className={cn(
                      'flex items-center gap-1 text-xs font-medium',
                      verdictColors[run.verdict.investment_view as keyof typeof verdictColors]
                    )}>
                      {VerdictIcon && <VerdictIcon className="w-3 h-3" />}
                      {run.verdict.investment_view}
                    </span>
                  ) : (
                    <span className="text-xs text-[var(--kp-text-muted)]">
                      {run.status}
                    </span>
                  )}
                </div>

                {/* Metadata */}
                <div className="flex items-center gap-3 text-xs text-[var(--kp-text-muted)]">
                  {run.started_at && (
                    <span>{formatDate(run.started_at)}</span>
                  )}
                  {(run.duration || run.total_cost) && (
                    <>
                      {run.duration && (
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatDuration(run.duration)}
                        </span>
                      )}
                      {run.total_cost && (
                        <span className="flex items-center gap-1">
                          <DollarSign className="w-3 h-3" />
                          {formatCost(run.total_cost)}
                        </span>
                      )}
                    </>
                  )}
                  {isActive && run.cost !== undefined && (
                    <span className="flex items-center gap-1 text-[var(--kp-green)]">
                      <DollarSign className="w-3 h-3" />
                      {formatCost(run.cost)}
                    </span>
                  )}
                </div>

                {/* Active run detail */}
                {isActive && run.current_agent && (
                  <div className="mt-2 text-xs text-[var(--kp-text-secondary)] truncate">
                    {run.current_agent}
                  </div>
                )}
              </motion.button>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
