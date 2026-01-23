// K+ Research Type Definitions

export type StageStatus = 'pending' | 'running' | 'complete' | 'error';

export interface Stage {
  id: number;
  name: string;
  shortName: string;
  status: StageStatus;
  startedAt?: string;
  completedAt?: string;
  duration?: number;
  detail?: string;
  cost?: number;
}

export interface RunConfig {
  ticker: string;
  budget: number;
  quarters: number;
  includeTranscripts: boolean;
  useDualDiscovery: boolean;
  useDeepResearch: boolean;
  maxVerticals?: number;
  transcriptsDir?: string;
  manualTranscripts?: Array<Record<string, unknown>>;
  requireDiscoveryApproval?: boolean;
  externalDiscoveryOverrides?: Record<string, string[]>;
  externalDiscoveryOverrideMode?: 'append' | 'replace';
}

export interface RunState {
  runId: string;
  ticker: string;
  status: 'idle' | 'running' | 'complete' | 'error';
  phase: string;
  startedAt?: string;
  completedAt?: string;
  budget: number;
  spent: number;
  stages: Stage[];
  currentStage?: number;
  error?: string;
}

export interface DiscoveredThread {
  thread_id: string;
  name: string;
  description: string;
  thread_type: 'segment' | 'optionality' | 'cross_cutting';
  priority: number;
  discovery_lens: string;
  is_official_segment: boolean;
  official_segment_name?: string;
  value_driver_hypothesis: string;
  research_questions: string[];
  evidence_ids?: string[];
}

export interface ResearchGroup {
  group_id: string;
  name: string;
  theme: string;
  vertical_ids: string[];
  key_questions: string[];
  grouping_rationale: string;
  shared_context: string;
  valuation_approach?: string;
  focus?: string;
}

export interface DiscoveryOutput {
  official_segments: string[];
  research_threads: DiscoveredThread[];
  research_groups: ResearchGroup[];
  cross_cutting_themes: string[];
  optionality_candidates: string[];
  data_gaps: string[];
  conflicting_signals?: string[];
  evidence_ids?: string[];
  thread_briefs?: unknown[];
  searches_performed?: Array<{ lens: string; query: string; key_finding?: string }>;
}

export interface VerticalAnalysis {
  thread_id: string;
  vertical_name: string;
  business_understanding: string;
  evidence_ids?: string[];
  overall_confidence: number;
}

export interface SynthesisOutput {
  full_report: string;
  investment_view: 'BUY' | 'HOLD' | 'SELL';
  conviction: 'high' | 'medium' | 'low' | 'high-medium' | 'medium-low';
  overall_confidence: number;
  thesis_summary: string;
  synthesizer_model: 'claude';  // Anthropic-only
}

export interface EditorialFeedback {
  preferred_synthesis: 'claude';  // Anthropic-only
  preference_reasoning: string;
  claude_score: number;
  key_differentiators: string[];
  revision_instructions: string;
  recommended_confidence: number;
  key_strengths: string[];
  key_weaknesses: string[];
}

export interface CompletedRun {
  runId: string;
  ticker: string;
  startedAt: string;
  completedAt: string;
  duration: number;
  totalCost: number;
  verdict: {
    investmentView: string;
    conviction: string;
    confidence: number;
  };
  reportPath: string;
}

export interface AgentConfig {
  name: string;
  model: string;
  stage: number;
  systemPrompt?: string;
  temperature?: number;
  maxTokens?: number;
}

export interface PipelineConfig {
  agents: AgentConfig[];
  budget: number;
  quarters: number;
  useDualDiscovery: boolean;
  useDeepResearch: boolean;
}

// WebSocket event types
export interface WSEvent {
  type: 'stage_update' | 'cost_update' | 'discovery_update' | 'synthesis_update' | 'error' | 'complete';
  payload: unknown;
}

export interface StageUpdatePayload {
  stage: number;
  stageName: string;
  status: StageStatus;
  detail?: string;
  cost?: number;
}

export interface CostUpdatePayload {
  spent: number;
  budget: number;
}
