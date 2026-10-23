export interface DeckEntry {
  modelId: string;
  modelName?: string;
  provider?: string;
  tier?: string;
  toolsSupported?: boolean;
  contextWindow?: number;
}

export interface StageConfig {
  pinnedModels?: string[];
  useDeck?: boolean;
}

export interface PipelineConfig {
  mode?: string;
  engineUrl?: string;
  workers?: number;
  timeout?: number;
  maxRetries?: number;
}

export interface ProfileData {
  version: string;
  name: string;
  description: string;
  deck: DeckEntry[];
  stages: Record<string, StageConfig>;
  pipeline: PipelineConfig;
}
