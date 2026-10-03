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
  /** 加载/操作错误。缺了它，sidecar 起不来时 accounts 保持 []，
      组件会渲染「暂无账号」，把故障伪装成空状态。 */
  const error = ref("");
  const selectedAccountId = ref<string | null>(null);
  let accountUnlisten: UnlistenFn | null = null;
  let initialized = false;

  async function fetchAccounts() {
    loading.value = true;
    error.value = "";
    try {
      accounts.value = await invoke<Account[]>("get_accounts");
    } catch (e) {
      error.value = `加载账号失败: ${e}`;
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function addAccount(cookie: string) {
    const account = await invoke<Account>("add_account", { cookie });
    accounts.value.push(account);
    // 同一 id 再次出现是合法复用，清掉删除标记避免任务集被误判为已删除
    useTasksStore().reviveAccountTasks(account.id);
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

  // running 的唯一真源是 account-state-changed 事件。
  // 原实现在 start/stel 成功后乐观写 running，但事件走 app_handle.emit、
  // 命令响应走 per-id pending map，两条不同 IPC 通道的到达顺序不受约束：
  // 「点启动后立刻点停止」时 stop 的响应先到置 false，随后启动那次的状态
  // 事件姗姗来迟改回 true —— 此后没有任何东西纠正它，anyRunning 永久为真，
  // 窗口再也无法关闭，只能杀进程。
  async function startMiner(accountId: string) {
    await invoke("start_miner", { accountId });
  }

  async function stopMiner(accountId: string) {
    await invoke("stop_miner", { accountId });
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
    error,
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
