'use client';

import { useEffect, useCallback, useRef } from 'react';
import { useResearchStore } from '@/store/research';
import api from '@/lib/api';
import type { StageStatus } from '@/types';

interface SSEEvent {
  type: string;
  timestamp: string;
  event_type: string;
  agent_name: string;
  stage: number;
  data: {
    stage_name?: string;
    status?: string;
    detail?: string;
    cost?: number;
    verdict?: {
      investment_view: string;
      conviction: string;
      confidence: number;
    };
    error?: string;
    traceback?: string;
  };
}

export function useRunStream(runId: string | null) {
  const cleanupRef = useRef<(() => void) | null>(null);
  const { updateStage, updateCost, completeRun, setError } = useResearchStore();

  const handleEvent = useCallback((event: SSEEvent) => {
    console.log('[SSE]', event.event_type, event);

    switch (event.event_type) {
      case 'stage_start':
      case 'stage_running':
        if (event.stage) {
          updateStage(event.stage, {
            status: 'running' as StageStatus,
            detail: event.data.detail,
          });
        }
        if (event.data.cost !== undefined) {
          updateCost(event.data.cost);
        }
        break;

      case 'stage_complete':
        if (event.stage) {
          updateStage(event.stage, {
            status: 'complete' as StageStatus,
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
        setError(event.data.error || 'Unknown error');
        break;

      case 'run_cancelled':
        setError('Run cancelled by user');
        break;
    }
  }, [updateStage, updateCost, completeRun, setError]);

  useEffect(() => {
    if (!runId) return;

    // Clean up previous stream
    if (cleanupRef.current) {
      cleanupRef.current();
    }

    // Start new stream
    const cleanup = api.streamRun(
      runId,
      (event) => handleEvent(event as unknown as SSEEvent),
      (error) => {
        console.error('[SSE Error]', error);
        setError(`Connection lost: ${error.message}`);
      }
    );

    cleanupRef.current = cleanup;

    return () => {
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
    };
  }, [runId, handleEvent, setError]);
}

export function useStartRun() {
  const { startRun } = useResearchStore();

  return useCallback(async (ticker: string, budget: number = 50) => {
    try {
      const result = await api.startRun({
        ticker: ticker.toUpperCase(),
        budget,
        quarters: 4,
        use_dual_discovery: true,
        use_deep_research: true,
      });

      startRun({
        ticker: ticker.toUpperCase(),
        budget,
        quarters: 4,
        includeTranscripts: true,
        useDualDiscovery: true,
        useDeepResearch: true,
      });

      return result.run_id;
    } catch (error) {
      console.error('Failed to start run:', error);
      throw error;
    }
  }, [startRun]);
}
