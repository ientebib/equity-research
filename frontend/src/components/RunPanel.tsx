'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, Square, Clock, DollarSign, TrendingUp, AlertCircle } from 'lucide-react';
import { cn, formatDuration, formatCost, getCostClass } from '@/lib/utils';
import { PipelineStages, PipelineProgress } from './PipelineStages';
import { useResearchStore } from '@/store/research';
import api, { type StageEvent } from '@/lib/api';
import type { StageStatus } from '@/types';

interface RunPanelProps {
  className?: string;
}

export function RunPanel({ className }: RunPanelProps) {
  const [ticker, setTicker] = useState('');
  const [budget, setBudget] = useState(50);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const { run, startRun, updateStage, updateCost, completeRun, setError: setRunError, setSelectedTab } = useResearchStore();

  // Timer for elapsed time
  useEffect(() => {
    if (!run || run.status !== 'running') return;

    const interval = setInterval(() => {
      if (run.startedAt) {
        const start = new Date(run.startedAt).getTime();
        setElapsed(Math.floor((Date.now() - start) / 1000));
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [run]);

  // Handle SSE events
  const handleEvent = useCallback((event: StageEvent) => {
    console.log('SSE Event:', event);

    switch (event.type) {
      case 'stage_update':
        if ((event.stage || event.data.stage) && event.data.status) {
          const status = event.data.status === 'complete'
            ? 'complete'
            : event.data.status === 'error'
              ? 'error'
              : 'running';
          updateStage((event.stage || event.data.stage) as number, {
            status: status as StageStatus,
            detail: event.data.detail,
          });
        }
        if (event.data.cost !== undefined) {
          updateCost(event.data.cost);
        }
        break;

      case 'run_complete':
        if (event.data.verdict) {
          completeRun({
            investmentView: event.data.verdict.investment_view,
            conviction: event.data.verdict.conviction,
            confidence: event.data.verdict.confidence,
          });
        }
        break;

      case 'run_error':
      case 'error':
        setRunError(event.data.error || event.data.message || 'Unknown error');
        break;
    }
  }, [updateStage, updateCost, completeRun, setRunError]);

  // Start a new run
  const handleStartRun = async () => {
    if (!ticker.trim()) {
      setError('Please enter a ticker symbol');
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      // Start run via API
      const result = await api.startRun({
        ticker: ticker.toUpperCase(),
        budget,
        quarters: 4,
        use_dual_discovery: true,
        use_deep_research: true,
      });

      // Update local state
      startRun({
        ticker: ticker.toUpperCase(),
        budget,
        quarters: 4,
        includeTranscripts: true,
        useDualDiscovery: true,
        useDeepResearch: true,
      });

      // Start SSE stream
      api.streamRun(result.run_id, handleEvent, (err) => {
        console.error('Stream error:', err);
        setError('Lost connection to server');
      });

    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start run');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Cancel active run
  const handleCancel = async () => {
    if (!run) return;

    try {
      await api.cancelRun(run.runId);
      setRunError('Run cancelled by user');
    } catch (e) {
      console.error('Failed to cancel:', e);
    }
  };

  const isRunning = run?.status === 'running';
  const isComplete = run?.status === 'complete';

  return (
    <div className={cn('kp-panel', className)}>
      {/* Header */}
      <div className="kp-panel-header flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={cn(
            'w-2 h-2 rounded-full',
            !run && 'bg-[var(--kp-text-muted)]',
            isRunning && 'bg-[var(--kp-green)] animate-pulse-soft',
            isComplete && 'bg-[var(--kp-cyan)]',
            run?.status === 'error' && 'bg-[var(--kp-red)]'
          )} />
          <h2 className="kp-display-sm">
            {!run && 'New Analysis'}
            {isRunning && `Analyzing ${run.ticker}`}
            {isComplete && `${run.ticker} Complete`}
            {run?.status === 'error' && 'Error'}
          </h2>
        </div>

        {/* Quick stats when running */}
        {isRunning && run && (
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5 text-[var(--kp-text-muted)]">
              <Clock className="w-3.5 h-3.5" />
              <span className="kp-mono">{formatDuration(elapsed)}</span>
            </div>
            <div className={cn('flex items-center gap-1.5', getCostClass(run.spent, run.budget))}>
              <DollarSign className="w-3.5 h-3.5" />
              <span className="kp-mono">{formatCost(run.spent)}</span>
              <span className="text-[var(--kp-text-muted)]">/ {formatCost(run.budget)}</span>
            </div>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-5">
        <AnimatePresence mode="wait">
          {/* Input form when no run active */}
          {!run && (
            <motion.div
              key="form"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-5"
            >
              {/* Ticker input */}
              <div>
                <label className="kp-label block mb-2">Ticker Symbol</label>
                <input
                  type="text"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  placeholder="AAPL"
                  className="kp-input w-full text-xl font-semibold tracking-wider"
                  maxLength={5}
                />
              </div>

              {/* Budget slider */}
              <div>
                <label className="kp-label block mb-2">
                  Budget: <span className="kp-mono text-[var(--kp-text)]">${budget}</span>
                </label>
                <input
                  type="range"
                  min={10}
                  max={100}
                  step={5}
                  value={budget}
                  onChange={(e) => setBudget(Number(e.target.value))}
                  className="w-full accent-[var(--kp-green)]"
                />
                <div className="flex justify-between text-xs text-[var(--kp-text-muted)] mt-1">
                  <span>$10</span>
                  <span>$100</span>
                </div>
              </div>

              {/* Error message */}
              {error && (
                <div className="flex items-center gap-2 text-[var(--kp-red)] text-sm">
                  <AlertCircle className="w-4 h-4" />
                  {error}
                </div>
              )}

              {/* Start button */}
              <button
                onClick={handleStartRun}
                disabled={isSubmitting || !ticker.trim()}
                className={cn(
                  'kp-btn kp-btn-primary w-full flex items-center justify-center gap-2',
                  (isSubmitting || !ticker.trim()) && 'opacity-50 cursor-not-allowed'
                )}
              >
                <Play className="w-4 h-4" />
                {isSubmitting ? 'Starting...' : 'Start Analysis'}
              </button>
            </motion.div>
          )}

          {/* Running state */}
          {isRunning && run && (
            <motion.div
              key="running"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-5"
            >
              {/* Compact progress */}
              <PipelineProgress stages={run.stages} />

              {/* Stage list */}
              <PipelineStages
                stages={run.stages}
              />

              {/* Cancel button */}
              <button
                onClick={handleCancel}
                className="kp-btn w-full flex items-center justify-center gap-2 text-[var(--kp-red)]"
              >
                <Square className="w-4 h-4" />
                Cancel Run
              </button>
            </motion.div>
          )}

          {/* Complete state */}
          {isComplete && run && (
            <motion.div
              key="complete"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-5"
            >
              {/* Summary */}
              <div className="text-center py-4">
                <div className="kp-ticker text-2xl mb-3">{run.ticker}</div>
                <div className="kp-verdict kp-verdict-buy">
                  <TrendingUp className="w-4 h-4" />
                  Analysis Complete
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-4">
                <div className="text-center p-3 rounded-lg bg-[var(--kp-elevated)]">
                  <div className="kp-label mb-1">Duration</div>
                  <div className="kp-mono text-lg">{formatDuration(elapsed)}</div>
                </div>
                <div className="text-center p-3 rounded-lg bg-[var(--kp-elevated)]">
                  <div className="kp-label mb-1">Cost</div>
                  <div className="kp-mono text-lg">{formatCost(run.spent)}</div>
                </div>
              </div>

              {/* View Report button */}
              <button
                onClick={() => setSelectedTab('report')}
                className="kp-btn kp-btn-primary w-full"
              >
                View Report
              </button>

              {/* New Analysis button */}
              <button
                onClick={() => {
                  useResearchStore.getState().resetRun();
                  setTicker('');
                }}
                className="kp-btn w-full"
              >
                New Analysis
              </button>
            </motion.div>
          )}

          {/* Error state */}
          {run?.status === 'error' && (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-5"
            >
              <div className="text-center py-4">
                <AlertCircle className="w-12 h-12 text-[var(--kp-red)] mx-auto mb-3" />
                <h3 className="text-lg font-semibold mb-2">Analysis Failed</h3>
                <p className="text-[var(--kp-text-muted)]">{run.error}</p>
              </div>

              <button
                onClick={() => {
                  useResearchStore.getState().resetRun();
                }}
                className="kp-btn w-full"
              >
                Try Again
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
