import { defineStore } from "pinia";
import { ref } from "vue";
import type { LogEntry } from "@/lib/types";

export const useLogsStore = defineStore("logs", () => {
  const logs = ref<LogEntry[]>([]);
  const maxLogs = 5000;

  function addLog(entry: LogEntry) {
    logs.value.push(entry);
    if (logs.value.length > maxLogs) {
      logs.value = logs.value.slice(-maxLogs);
    }
  }

  function clear() {
    logs.value = [];
  }

  return { logs, addLog, clear };
});

