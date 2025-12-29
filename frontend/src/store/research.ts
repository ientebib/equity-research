import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type {
  RunState,
  Stage,
  DiscoveryOutput,
  SynthesisOutput,
  EditorialFeedback,
  CompletedRun,
  RunConfig
} from '@/types';

const DEFAULT_STAGES: Stage[] = [
  { id: 1, name: 'Data Collection', shortName: 'DATA', status: 'pending' },
  { id: 2, name: 'Discovery', shortName: 'DISC', status: 'pending' },
  { id: 3, name: 'Deep Research', shortName: 'DEEP', status: 'pending' },
  { id: 4, name: 'Dual Synthesis', shortName: 'SYNTH', status: 'pending' },
  { id: 5, name: 'Editorial Review', shortName: 'EDIT', status: 'pending' },
  { id: 6, name: 'Final Report', shortName: 'FINAL', status: 'pending' },
];

interface ResearchStore {
  // Current run state
  run: RunState | null;
  discovery: DiscoveryOutput | null;
  claudeSynthesis: SynthesisOutput | null;
  gptSynthesis: SynthesisOutput | null;
  editorialFeedback: EditorialFeedback | null;
  finalReport: string | null;

  // History
  completedRuns: CompletedRun[];

  // UI state
  selectedTab: 'pipeline' | 'report' | 'config';
  selectedRunId: string | null;

  // Actions
  startRun: (config: RunConfig) => void;
  updateStage: (stageId: number, update: Partial<Stage>) => void;
  updateCost: (spent: number) => void;
  setDiscovery: (discovery: DiscoveryOutput) => void;
  setClaudeSynthesis: (synthesis: SynthesisOutput) => void;
  setGptSynthesis: (synthesis: SynthesisOutput) => void;
  setEditorialFeedback: (feedback: EditorialFeedback) => void;
  setFinalReport: (report: string) => void;
  completeRun: (verdict: CompletedRun['verdict']) => void;
  setError: (error: string) => void;
  resetRun: () => void;
  setSelectedTab: (tab: 'pipeline' | 'report' | 'config') => void;
  loadRun: (runId: string) => void;
}

export const useResearchStore = create<ResearchStore>()(
  persist(
    (set, get) => ({
      // Initial state
      run: null,
      discovery: null,
      claudeSynthesis: null,
      gptSynthesis: null,
      editorialFeedback: null,
      finalReport: null,
      completedRuns: [],
      selectedTab: 'pipeline',
      selectedRunId: null,

      startRun: (config) => {
        const runId = `run_${Date.now()}_${config.ticker}`;
        set({
          run: {
            runId,
            ticker: config.ticker,
            status: 'running',
            phase: 'INIT',
            startedAt: new Date().toISOString(),
            budget: config.budget,
            spent: 0,
            stages: DEFAULT_STAGES.map(s => ({ ...s, status: 'pending' as const })),
            currentStage: 1,
          },
          discovery: null,
          claudeSynthesis: null,
          gptSynthesis: null,
          editorialFeedback: null,
          finalReport: null,
          selectedTab: 'pipeline',
        });
      },

      updateStage: (stageId, update) => {
        const { run } = get();
        if (!run) return;

        set({
          run: {
            ...run,
            stages: run.stages.map(s =>
              s.id === stageId ? { ...s, ...update } : s
            ),
            currentStage: update.status === 'running' ? stageId : run.currentStage,
          },
        });
      },

      updateCost: (spent) => {
        const { run } = get();
        if (!run) return;
        set({ run: { ...run, spent } });
      },

      setDiscovery: (discovery) => set({ discovery }),
      setClaudeSynthesis: (synthesis) => set({ claudeSynthesis: synthesis }),
      setGptSynthesis: (synthesis) => set({ gptSynthesis: synthesis }),
      setEditorialFeedback: (feedback) => set({ editorialFeedback: feedback }),
      setFinalReport: (report) => set({ finalReport: report }),

      completeRun: (verdict) => {
        const { run, completedRuns } = get();
        if (!run) return;

        const completedAt = new Date().toISOString();
        const duration = run.startedAt
          ? (new Date(completedAt).getTime() - new Date(run.startedAt).getTime()) / 1000
          : 0;

        const completedRun: CompletedRun = {
          runId: run.runId,
          ticker: run.ticker,
          startedAt: run.startedAt || completedAt,
          completedAt,
          duration,
          totalCost: run.spent,
          verdict,
          reportPath: `/output/${run.runId}/report.md`,
        };

        set({
          run: {
            ...run,
            status: 'complete',
            completedAt,
            stages: run.stages.map(s => ({ ...s, status: 'complete' as const })),
          },
          completedRuns: [completedRun, ...completedRuns].slice(0, 50), // Keep last 50 runs
          selectedTab: 'report',
        });
      },

      setError: (error) => {
        const { run } = get();
        if (!run) return;
        set({
          run: {
            ...run,
            status: 'error',
            error,
          },
        });
      },

      resetRun: () => set({
        run: null,
        discovery: null,
        claudeSynthesis: null,
        gptSynthesis: null,
        editorialFeedback: null,
        finalReport: null,
        selectedTab: 'pipeline',
      }),

      setSelectedTab: (tab) => set({ selectedTab: tab }),

      loadRun: (runId) => {
        const { completedRuns } = get();
        const run = completedRuns.find(r => r.runId === runId);
        if (run) {
          set({ selectedRunId: runId, selectedTab: 'report' });
        }
      },
    }),
    {
      name: 'kp-research-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        completedRuns: state.completedRuns,
        run: state.run?.status === 'running' ? state.run : null,
        discovery: state.run?.status === 'running' ? state.discovery : null,
        claudeSynthesis: state.run?.status === 'running' ? state.claudeSynthesis : null,
        gptSynthesis: state.run?.status === 'running' ? state.gptSynthesis : null,
        finalReport: state.run?.status === 'running' ? state.finalReport : null,
      }),
    }
  )
);
