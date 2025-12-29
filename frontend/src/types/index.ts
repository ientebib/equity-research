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
  threadId: string;
  name: string;
  description: string;
  threadType: 'SEGMENT' | 'OPTIONALITY' | 'CROSS_CUTTING';
  priority: number;
  discoveryLens: string;
  isOfficialSegment: boolean;
  valueDriverHypothesis: string;
  researchQuestions: string[];
}

export interface ResearchGroup {
  groupId: string;
  name: string;
  theme: string;
  verticalIds: string[];
  keyQuestions: string[];
  groupingRationale: string;
  sharedContext: string;
}

export interface DiscoveryOutput {
  officialSegments: string[];
  researchThreads: DiscoveredThread[];
  researchGroups: ResearchGroup[];
  crossCuttingThemes: string[];
  optionalityCandidates: string[];
  dataGaps: string[];
}

export interface VerticalAnalysis {
  threadId: string;
  verticalName: string;
  businessUnderstanding: string;
  overallConfidence: number;
}

export interface SynthesisOutput {
  fullReport: string;
  investmentView: 'BUY' | 'HOLD' | 'SELL';
  conviction: 'high' | 'medium' | 'low' | 'high-medium' | 'medium-low';
  overallConfidence: number;
  thesisSummary: string;
  synthesizerModel: 'claude' | 'gpt';
}

export interface EditorialFeedback {
  preferredSynthesis: 'claude' | 'gpt';
  preferenceReasoning: string;
  claudeScore: number;
  gptScore: number;
  keyDifferentiators: string[];
  revisionInstructions: string;
  recommendedConfidence: number;
  keyStrengths: string[];
  keyWeaknesses: string[];
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
