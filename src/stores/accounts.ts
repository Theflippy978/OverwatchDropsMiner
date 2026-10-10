import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { Account, AccountStatus } from "@/lib/types";
import { useLogsStore } from "@/stores/logs";
import { useTasksStore } from "@/stores/tasks";
import { formatIpcError } from "@/lib/ipc-error";

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
      error.value = formatIpcError(e, "加载账号失败");
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

  /** 按给定 id 顺序重排本地数组（纯本地，不落盘）。
   *
   *  **必须只在集合一致时调用**：集合不一致时缺的账号会被静默丢掉。
   *  调用方（拖拽组件 / reorderAccounts）已保证这一点。 */
  function applyAccountOrder(orderedIds: string[]): void {
    const byId = new Map(accounts.value.map((a) => [a.id, a]));
    const next: Account[] = [];
    for (const id of orderedIds) {
      const account = byId.get(id);
      if (account) next.push(account);
    }
    accounts.value = next;
  }

  /** 把账号顺序改成 `orderedIds` 并落盘。
   *
   *  **乐观更新 + 失败回滚**：拖拽是高频手势，等一次 IPC 往返再动界面会「粘手」，
   *  所以先改本地顺序让界面立刻响应，失败再回滚。
   *  （与 `startMiner` 刻意**不**做乐观更新的理由不同：那里 `running` 的真源是
   *  `account-state-changed` 事件通道，而顺序的真源就是这个数组本身。）
   *
   *  **`rollbackTo` 必须能被显式指定**：拖拽场景下 SortableJS 已经先把数组
   *  改成新顺序了，等进到这里时「调用前的顺序」已经是新顺序 —— 拿它当回滚点
   *  等于不回滚。所以组件要把**拖拽开始前**记下的顺序传进来。
   *
   *  失败必须回滚：否则界面显示新顺序、磁盘还是旧顺序，重启即变回去，
   *  且此后任何一次成功保存都会把这个中间顺序悄悄持久化。 */
  async function reorderAccounts(
    orderedIds: string[],
    rollbackTo?: string[]
  ): Promise<void> {
    const fallback = rollbackTo ?? accounts.value.map((a) => a.id);
    applyAccountOrder(orderedIds);
    try {
      await invoke("reorder_accounts", { orderedIds });
    } catch (e) {
      applyAccountOrder(fallback);
      throw e;
    }
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
    reorderAccounts,
    startMiner,
    stopMiner,
    getStatus,
    browserCapture,
    initListeners,
    dispose,
  };
});
