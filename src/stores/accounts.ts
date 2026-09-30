import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { Account, AccountStatus } from "@/lib/types";
import { useLogsStore } from "@/stores/logs";
import { useTasksStore } from "@/stores/tasks";

export const useAccountsStore = defineStore("accounts", () => {
  const accounts = ref<Account[]>([]);
  const loading = ref(false);
  const selectedAccountId = ref<string | null>(null);
  let accountUnlisten: UnlistenFn | null = null;
  let initialized = false;

  async function fetchAccounts() {
    loading.value = true;
    try {
      accounts.value = await invoke<Account[]>("get_accounts");
    } finally {
      loading.value = false;
    }
  }

  async function addAccount(cookie: string) {
    const account = await invoke<Account>("add_account", { cookie });
    accounts.value.push(account);
    return account;
  }

  async function removeAccount(accountId: string) {
    const account = accounts.value.find((a) => a.id === accountId);
    if (account?.running) {
      await invoke("stop_miner", { accountId });
    }
    await invoke("remove_account", { accountId });
    accounts.value = accounts.value.filter((a) => a.id !== accountId);
    if (selectedAccountId.value === accountId) {
      selectedAccountId.value = null;
    }
    useLogsStore().clearByAccount(accountId);
    useTasksStore().clearAccountTasks(accountId);
  }

  async function renameAccount(accountId: string, remark: string): Promise<Account> {
    const account = await invoke<Account>("rename_account", { accountId, remark });
    const index = accounts.value.findIndex((a) => a.id === accountId);
    if (index >= 0) accounts.value[index] = account;
    return account;
  }

  async function startMiner(accountId: string) {
    await invoke("start_miner", { accountId });
    const account = accounts.value.find((a) => a.id === accountId);
    if (account) account.running = true;
  }

  async function stopMiner(accountId: string) {
    await invoke("stop_miner", { accountId });
    const account = accounts.value.find((a) => a.id === accountId);
    if (account) account.running = false;
  }

  async function getStatus(accountId: string): Promise<AccountStatus> {
    return await invoke<AccountStatus>("get_account_status", { accountId });
  }

  async function browserCapture(browser?: string): Promise<string> {
    return await invoke<string>("browser_capture", { browser });
  }

  // 监听 sidecar 转发的账号状态事件（幂等）
  async function initListeners() {
    if (initialized) return;
    initialized = true;
    try {
      accountUnlisten = await listen<{ account_id: string; running: boolean }>(
        "account-state-changed",
        (event) => {
          const { account_id, running } = event.payload;
          const account = accounts.value.find((a) => a.id === account_id);
          if (account) account.running = running;
        }
      );
    } catch (e) {
      initialized = false;
      console.error("注册账号状态监听失败:", e);
    }
  }

  function dispose() {
    if (accountUnlisten) {
      accountUnlisten();
      accountUnlisten = null;
    }
    initialized = false;
  }

  return {
    accounts,
    loading,
    selectedAccountId,
    fetchAccounts,
    addAccount,
    removeAccount,
    renameAccount,
    startMiner,
    stopMiner,
    getStatus,
    browserCapture,
    initListeners,
    dispose,
  };
});
