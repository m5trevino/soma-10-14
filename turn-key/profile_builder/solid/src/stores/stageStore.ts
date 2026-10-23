import { createSignal } from "solid-js";

export function useStageStore() {
  const [stages, setStages] = createSignal<Record<string, any>>({});

  return {
    stages,
    setStages,
    addStage: (name: string, config: any) =>
      setStages({ ...stages(), [name]: config }),
    removeStage: (name: string) => {
      const newStages = { ...stages() };
      delete newStages[name];
      setStages(newStages);
    },
    updateStage: (name: string, config: any) =>
      setStages({ ...stages(), [name]: config }),
  };
}
