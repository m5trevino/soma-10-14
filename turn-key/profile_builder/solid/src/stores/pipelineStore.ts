import { createSignal } from "solid-js";

export function defaultPipeline(): Record<string, any> {
  return {
    mode: "balanced",
    engineUrl: "http://engine.save-aichats.com:3099",
    workers: 1,
    timeout: 180,
    maxRetries: 10,
  };
}

export function usePipelineStore() {
  const [config, setConfig] = createSignal<any>(defaultPipeline());

  return {
    config,
    setConfig,
    updateConfig: (partial: Record<string, any>) =>
      setConfig({ ...config(), ...partial }),
  };
}
