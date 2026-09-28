import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { GuiConfigValues } from "@/lib/types";

export const useConfigStore = defineStore("config", () => {
  const config = ref<GuiConfigValues>({
    cookie: "",
    rooms_text: "",
    thread_count_text: "60",
    reconnect_delay_text: "8",
    task_ids_text: "",
    task_query_interval_text: "30",
    notify_urls_text: "",
    notify_on_task_complete: true,
    verbose: false,
    auto_claim_rewards: false,
  });

  const loading = ref(false);

  async function load() {
    loading.value = true;
    try {
      config.value = await invoke<GuiConfigValues>("load_config");
    } finally {
      loading.value = false;
    }
  }

  async function save() {
    await invoke("save_config", { config: config.value });
  }

  return { config, loading, load, save };
});
