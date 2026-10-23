import { createSignal, onMount } from "solid-js";
import { useDeckStore } from "../stores/deckStore";
import { useStageStore } from "../stores/stageStore";
import { usePipelineStore, defaultPipeline } from "../stores/pipelineStore";

const SERVER_URL = "http://localhost:8080";

function buildProfile() {
  const deck = useDeckStore();
  const stages = useStageStore();
  const pipeline = usePipelineStore();
  return {
    version: "1.0.0",
    name: profileName() || "",
    description: profileDescription() || "",
    deck: deck.deck(),
    stages: stages.stages(),
    pipeline: pipeline.config(),
  };
}

const [profileName, setProfileName] = createSignal("");
const [profileDescription, setProfileDescription] = createSignal("");
const [unsaved, setUnsaved] = createSignal(false);
const [profilesList, setProfilesList] = createSignal<string[]>([]);
const [activeProfile, setActiveProfile] = createSignal<string | null>(null);
const [profilePath, setProfilePath] = createSignal("");

async function loadProfilesList() {
  try {
    const res = await fetch(`${SERVER_URL}/api/profiles/list`);
    const data = await res.json();
    setProfilesList(data.profiles || []);
  } catch {
    setProfilesList([]);
  }
}

async function loadProfilePath() {
  try {
    const res = await fetch(`${SERVER_URL}/api/profiles/path`);
    const data = await res.json();
    setProfilePath(data.path || "");
  } catch {
    setProfilePath("");
  }
}

async function saveProfile() {
  const name = profileName() || "default";
  const filename = `${name}.json`;
  const profile = buildProfile();
  try {
    const res = await fetch(`${SERVER_URL}/api/profiles/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: filename, profile }),
    });
    if (res.ok) {
      const data = await res.json();
      setUnsaved(false);
      await loadProfilesList();
      setActiveProfile(filename);
      const savePath = data.path || profilePath();
      if (savePath) {
        alert(`Profile saved to:\n${savePath}/${filename}`);
      }
    } else {
      alert("Failed to save profile");
    }
  } catch {
    alert("Failed to save profile: server unreachable");
  }
}

async function importProfile(data: Record<string, any>) {
  const deck = useDeckStore();
  const stages = useStageStore();
  const pipeline = usePipelineStore();

  setProfileName(data.name || "");
  setProfileDescription(data.description || "");
  deck.setDeck(data.deck || []);
  stages.setStages(data.stages || {});
  pipeline.setConfig(data.pipeline || defaultPipeline().pipeline);
  setUnsaved(true);
}

async function loadExistingProfile(filename: string) {
  try {
    const res = await fetch(
      `${SERVER_URL}/api/profiles/load?name=${encodeURIComponent(filename)}`,
    );
    if (!res.ok) {
      alert(`Failed to load profile: ${filename}`);
      return;
    }
    const data = await res.json();
    await importProfile(data);
    setActiveProfile(filename);
  } catch {
    alert("Failed to load profile");
  }
}

async function deleteProfile(filename: string) {
  try {
    const res = await fetch(
      `${SERVER_URL}/api/profiles/delete?name=${encodeURIComponent(filename)}`,
      { method: "DELETE" },
    );
    if (res.ok) {
      if (activeProfile() === filename) {
        setActiveProfile(null);
      }
      await loadProfilesList();
    } else {
      alert("Failed to delete profile");
    }
  } catch {
    alert("Failed to delete profile");
  }
}

export default function ProfileIO() {
  onMount(() => {
    loadProfilesList();
    loadProfilePath();
  });

  function handleNew() {
    setProfileName("");
    setProfileDescription("");
    useDeckStore().setDeck([]);
    useStageStore().setStages({});
    usePipelineStore().setConfig(defaultPipeline());
    setUnsaved(false);
    setActiveProfile(null);
  }

  function handleImport() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,.yaml,.yml";
    input.onchange = async (e: any) => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        await importProfile(data);
      } catch {
        alert("Failed to parse profile file");
      }
    };
    input.click();
  }

  async function handleExport() {
    const name = (profileName() || "turnkey-profile")
      .replace(/[^a-zA-Z0-9_-]/g, "_")
      .replace(/\.json$/, "");
    await saveProfile();
    setProfileName(name);
  }

  return (
    <div class="panel" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
      <input
        type="text"
        placeholder="Profile name..."
        style="flex:1;min-width:150px"
        value={profileName()}
        onInput={(e) => {
          setProfileName(e.currentTarget.value);
          setUnsaved(true);
        }}
      />
      <input
        type="text"
        placeholder="Description..."
        style="flex:2;min-width:200px"
        value={profileDescription()}
        onInput={(e) => {
          setProfileDescription(e.currentTarget.value);
          setUnsaved(true);
        }}
      />
      <button onclick={handleNew}>New</button>
      <button onclick={handleImport}>Import</button>
      <button class="primary" onclick={handleExport}>Save</button>
      {unsaved() && (
        <span class="badge" style="background:var(--yellow);color:#000">
          Unsaved
        </span>
      )}
      {profilePath() && (
        <span class="badge" style="background:var(--gray);color:#fff;font-size:0.8em">
          Saved to: {profilePath()}
        </span>
      )}
    </div>
  );
}
