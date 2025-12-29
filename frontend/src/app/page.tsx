'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Settings,
  PanelRightClose,
  PanelRightOpen,
  Clock,
  DollarSign,
} from 'lucide-react';
import { Logo } from '@/components/Logo';
import { RunHistory } from '@/components/RunHistory';
import { PipelineStages, PipelineProgress } from '@/components/PipelineStages';
import { AgentActivity } from '@/components/AgentActivity';
import { ReportViewer } from '@/components/ReportViewer';
import { NewRunModal } from '@/components/NewRunModal';
import { useResearchStore } from '@/store/research';
import { useRunStream, useStartRun } from '@/hooks/useRun';
import { cn, formatDuration, formatCost, getCostClass } from '@/lib/utils';
import api from '@/lib/api';

type View = 'monitor' | 'report';

export default function Dashboard() {
  const [showModal, setShowModal] = useState(false);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [currentView, setCurrentView] = useState<View>('monitor');
  const [elapsed, setElapsed] = useState(0);
  const [events, setEvents] = useState<any[]>([]);

  const { run, resetRun } = useResearchStore();
  const startRun = useStartRun();

  // Stream events for active run
  useRunStream(run?.status === 'running' ? run.runId : null);

  // Elapsed timer
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

  // Fetch events for active run
  useEffect(() => {
    if (!run || run.status !== 'running') {
      setEvents([]);
      return;
    }

    const cleanup = api.streamRun(
      run.runId,
      (event) => {
        setEvents(prev => [...prev.slice(-100), event]);
      },
      (error) => {
        console.error('Stream error:', error);
      }
    );

    return cleanup;
  }, [run?.runId, run?.status]);

  // Handle starting a new run
  const handleStartRun = useCallback(async (
    ticker: string,
    budget: number,
    options: { quarters: number; useDualDiscovery: boolean; useDeepResearch: boolean }
  ) => {
    const runId = await startRun(ticker, budget);
    setSelectedRunId(runId);
    setCurrentView('monitor');
    setEvents([]);
  }, [startRun]);

  // Handle selecting a run from history
  const handleSelectRun = useCallback((runId: string) => {
    setSelectedRunId(runId);
    // If it's a completed run, show the report
    // If it's active, show the monitor
    api.getRun(runId).then(data => {
      if (data.status === 'complete') {
        setCurrentView('report');
      } else {
        setCurrentView('monitor');
      }
    });
  }, []);

  // Determine what to show in main area
  const isRunning = run?.status === 'running';
  const showReport = currentView === 'report' && selectedRunId;
  const showMonitor = currentView === 'monitor' && run;

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="h-14 flex-shrink-0 border-b border-[var(--kp-border)] bg-[var(--kp-surface)] flex items-center justify-between px-4">
        <Logo size="sm" />

        {/* Center: Active run info */}
        {isRunning && run && (
          <div className="flex items-center gap-6">
            <span className="kp-ticker">{run.ticker}</span>

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

            <PipelineProgress stages={run.stages} className="w-48" />
          </div>
        )}

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setRightPanelOpen(!rightPanelOpen)}
            className="p-2 rounded hover:bg-[var(--kp-elevated)] transition-colors"
            title={rightPanelOpen ? 'Hide panel' : 'Show panel'}
          >
            {rightPanelOpen ? (
              <PanelRightClose className="w-5 h-5 text-[var(--kp-text-muted)]" />
            ) : (
              <PanelRightOpen className="w-5 h-5 text-[var(--kp-text-muted)]" />
            )}
          </button>
          <button className="p-2 rounded hover:bg-[var(--kp-elevated)] transition-colors">
            <Settings className="w-5 h-5 text-[var(--kp-text-muted)]" />
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left sidebar: Run history */}
        <aside className="w-64 flex-shrink-0 border-r border-[var(--kp-border)] bg-[var(--kp-surface)]">
          <RunHistory
            onSelectRun={handleSelectRun}
            onNewRun={() => setShowModal(true)}
            selectedRunId={selectedRunId}
            activeRunId={run?.runId}
          />
        </aside>

        {/* Center: Main content area */}
        <main className="flex-1 overflow-hidden bg-[var(--kp-abyss)]">
          <AnimatePresence mode="wait">
            {/* Empty state */}
            {!showReport && !showMonitor && (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full flex flex-col items-center justify-center text-center p-8"
              >
                <div className="max-w-md">
                  <h2 className="kp-display text-2xl mb-4">Welcome to K+ Research</h2>
                  <p className="text-[var(--kp-text-secondary)] mb-6">
                    AI-powered equity research with dual-synthesis and editorial review.
                    Start a new analysis or select a previous run from the sidebar.
                  </p>
                  <button
                    onClick={() => setShowModal(true)}
                    className="kp-btn kp-btn-primary text-lg px-8 py-3"
                  >
                    Start New Analysis
                  </button>
                </div>
              </motion.div>
            )}

            {/* Pipeline monitor */}
            {showMonitor && run && (
              <motion.div
                key="monitor"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="h-full flex flex-col p-6"
              >
                {/* Stage list */}
                <div className="kp-panel mb-6">
                  <div className="kp-panel-header">
                    <h3 className="kp-display-sm">Pipeline Stages</h3>
                  </div>
                  <div className="p-4">
                    <PipelineStages
                      stages={run.stages}
                      currentStage={run.currentStage}
                    />
                  </div>
                </div>

                {/* Controls */}
                <div className="flex gap-3">
                  {run.status === 'running' && (
                    <button
                      onClick={() => api.cancelRun(run.runId)}
                      className="kp-btn text-[var(--kp-red)]"
                    >
                      Cancel Run
                    </button>
                  )}
                  {run.status === 'complete' && (
                    <button
                      onClick={() => {
                        setSelectedRunId(run.runId);
                        setCurrentView('report');
                      }}
                      className="kp-btn kp-btn-primary"
                    >
                      View Report
                    </button>
                  )}
                  {run.status === 'error' && (
                    <div className="flex items-center gap-3 text-[var(--kp-red)]">
                      <span>Error: {run.error}</span>
                      <button onClick={resetRun} className="kp-btn">
                        Dismiss
                      </button>
                    </div>
                  )}
                </div>
              </motion.div>
            )}

            {/* Report viewer */}
            {showReport && selectedRunId && (
              <motion.div
                key="report"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full"
              >
                <ReportViewer runId={selectedRunId} />
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* Right panel: Agent activity */}
        <AnimatePresence>
          {rightPanelOpen && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 380, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex-shrink-0 border-l border-[var(--kp-border)] bg-[var(--kp-surface)] overflow-hidden"
            >
              <div className="w-[380px] h-full">
                <AgentActivity events={events} />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* New run modal */}
      <NewRunModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        onStart={handleStartRun}
      />
    </div>
  );
}
