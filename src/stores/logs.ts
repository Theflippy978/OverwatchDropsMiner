import { defineStore } from "pinia";
import { ref } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { LogEntry } from "@/lib/types";

export const useLogsStore = defineStore("logs", () => {
  const logs = ref<LogEntry[]>([]);
  const maxLogs = 5000;
  let unlisten: UnlistenFn | null = null;
  let initialized = false;

  function addLog(entry: LogEntry) {
    logs.value.push(entry);
    if (logs.value.length > maxLogs) {
      logs.value = logs.value.slice(-maxLogs);
    }
  }

  function clear() {
    logs.value = [];
  }

  // 监听 sidecar 转发的 log-entry 事件（幂等）
  async function initListeners() {
    if (initialized) return;
    initialized = true;
    try {
      unlisten = await listen<LogEntry>("log-entry", (event) => {
        addLog(event.payload);
      });
    } catch (e) {
      initialized = false;
      console.error("注册日志监听失败:", e);
    }
  }

  function dispose() {
    if (unlisten) {
      unlisten();
      unlisten = null;
    }
    initialized = false;
  }

  return { logs, addLog, clear, initListeners, dispose };
});
