import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { LogEntry } from "@/lib/types";

export interface StoredLog extends LogEntry {
  seq: number;
}

export const useLogsStore = defineStore("logs", () => {
  const logs = ref<StoredLog[]>([]);
  const maxLogs = 5000;
  const filterAccountId = ref<string | null>(null);
  let unlisten: UnlistenFn | null = null;
  let initialized = false;
  let nextSeq = 0;
  const buffer: StoredLog[] = [];
  let flushTimer: number | null = null;

  const filteredLogs = computed(() => {
    if (!filterAccountId.value) return logs.value;
    return logs.value.filter((l) => l.account_id === filterAccountId.value);
  });

  function flush() {
    flushTimer = null;
    if (buffer.length === 0) return;
    logs.value.push(...buffer);
    buffer.length = 0;
    const overflow = logs.value.length - maxLogs;
    if (overflow > 0) {
      logs.value.splice(0, overflow);
    }
  }

  function addLog(entry: LogEntry) {
    buffer.push({ ...entry, seq: nextSeq++ });
    if (flushTimer === null) {
      flushTimer = window.setTimeout(flush, 120);
    }
  }

  function clear() {
    buffer.length = 0;
    if (flushTimer !== null) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    logs.value = [];
  }

  function setFilter(accountId: string | null) {
    filterAccountId.value = accountId;
  }

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
    clear();
  }

  return { logs, filteredLogs, filterAccountId, addLog, clear, setFilter, initListeners, dispose };
});
