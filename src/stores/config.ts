import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { GuiConfigValues } from "@/lib/types";

function clampInt(value: string, defaultVal: number, min: number, max: number): string {
  const n = parseInt(value, 10);
  if (isNaN(n)) return String(defaultVal);
  return String(Math.max(min, Math.min(max, n)));
}

/** 任务 ID 文本去重 + 稳定排序（与后端 _normalize_task_ids_text 一致） */
function normalizeTaskIds(value: string): string {
  const parts = value
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  return Array.from(new Set(parts)).sort().join(",");
}

export const useConfigStore = defineStore("config", () => {
  const config = ref<GuiConfigValues>({
    cookie: "",
    rooms_text: "23612045",
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

  function validateConfig(): string | null {
    const rooms = config.value.rooms_text.split(",").map((r) => r.trim()).filter((r) => r.length > 0);
    if (rooms.length === 0) {
      return "房间号不能为空";
    }
    for (const room of rooms) {
      if (!/^\d+$/.test(room)) {
        return `房间号格式错误: ${room}`;
      }
      if (parseInt(room, 10) <= 0) {
        return `房间号必须大于 0: ${room}`;
      }
    }
    const threads = parseInt(config.value.thread_count_text, 10);
     if (isNaN(threads) || threads < 1 || threads > 256) {
       return "线程数必须在 1-256 之间";
     }
     const totalConnections = rooms.length * threads;
     if (totalConnections > 256) {
       return `总连接数（房间数 × 线程数）不能超过 256，当前: ${totalConnections}`;
     }
    return null;
  }

  async function save() {
    // 数值字段统一钳制
    config.value.thread_count_text = clampInt(config.value.thread_count_text, 60, 1, 256);
    config.value.reconnect_delay_text = clampInt(config.value.reconnect_delay_text, 8, 1, 3600);
    config.value.task_query_interval_text = clampInt(config.value.task_query_interval_text, 30, 10, 3600);
    // 任务 ID 文本去重 + 排序，避免仅顺序不同的输入被判为变更
    config.value.task_ids_text = normalizeTaskIds(config.value.task_ids_text);
    // 配置验证
    const error = validateConfig();
    if (error) {
      throw new Error(error);
    }
    try {
      await invoke("save_config", { config: config.value });
    } catch (e) {
      // 让调用方（ConfigForm）能提示保存失败，而不是静默丢弃
      throw new Error(`保存配置失败: ${e}`);
    }
    // 回读确认（后端会重新钳制并返回真实落盘值）
    await load();
  }

  return { config, loading, load, ensureLoaded, save };
});
