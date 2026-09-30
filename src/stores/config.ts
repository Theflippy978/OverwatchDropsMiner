import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { GuiConfigValues } from "@/lib/types";

function clampInt(value: string, defaultVal: number, min: number, max: number): string {
  const n = parseInt(value, 10);
  if (isNaN(n)) return String(defaultVal);
  return String(Math.max(min, Math.min(max, n)));
}

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
  let loaded = false;

  async function load() {
    loading.value = true;
    try {
      config.value = await invoke<GuiConfigValues>("load_config");
      loaded = true;
    } finally {
      loading.value = false;
    }
  }

  // 幂等加载：多个组件 onMounted 竞争时只发一次 load_config
  async function ensureLoaded() {
    if (!loaded) await load();
  }

  async function save() {
    // 数值字段统一钳制
    config.value.thread_count_text = clampInt(config.value.thread_count_text, 60, 1, 128);
    config.value.reconnect_delay_text = clampInt(config.value.reconnect_delay_text, 8, 1, 3600);
    config.value.task_query_interval_text = clampInt(config.value.task_query_interval_text, 30, 10, 3600);
    await invoke("save_config", { config: config.value });
    // 回读确认
    await load();
  }

  return { config, loading, load, ensureLoaded, save };
});
