import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { Account, AccountStatus } from "@/lib/types";

export const useAccountsStore = defineStore("accounts", () => {
  const accounts = ref<Account[]>([]);
  const loading = ref(false);
  const selectedAccountId = ref<string | null>(null);

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
    await invoke("remove_account", { accountId });
    accounts.value = accounts.value.filter((a) => a.id !== accountId);
  }

  async function startMiner(accountId: string, config: any) {
    await invoke("start_miner", { accountId, config });
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

  async function browserCapture(): Promise<string> {
    return await invoke<string>("browser_capture");
  }

  return {
    accounts,
    loading,
    selectedAccountId,
    fetchAccounts,
    addAccount,
    removeAccount,
    startMiner,
    stopMiner,
    getStatus,
    browserCapture,
  };
});
