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

  function clearByAccount(accountId: string) {
    // 只清该账号：缓冲区里其它账号的日志要保留，不能被连带丢弃
    if (buffer.length > 0) {
      const kept = buffer.filter((l) => l.account_id !== accountId);
      buffer.length = 0;
      buffer.push(...kept);
      if (kept.length > 0 && flushTimer === null) {
        flushTimer = window.setTimeout(flush, 120);
      }
    }
    logs.value = logs.value.filter((l) => l.account_id !== accountId);
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

  return { logs, filteredLogs, filterAccountId, addLog, clear, clearByAccount, setFilter, initListeners, dispose };
});
