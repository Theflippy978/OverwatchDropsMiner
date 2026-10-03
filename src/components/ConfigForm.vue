<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { save, open } from "@tauri-apps/plugin-dialog";
import { useConfigStore } from "@/stores/config";
import { useAccountsStore } from "@/stores/accounts";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const configStore = useConfigStore();
const accountsStore = useAccountsStore();

const anyRunning = computed(() =>
  accountsStore.accounts.some((a) => a.running)
);

// 「禁用任务完成通知」= notify_on_task_complete 的反义（对齐旧版复选框语义）
const disableTaskNotify = computed({
  get: () => !configStore.config.notify_on_task_complete,
  set: (v: boolean) => {
    configStore.config.notify_on_task_complete = !v;
  },
});

const testing = ref(false);
const testResult = ref("");

async function handleTest() {
  testing.value = true;
  testResult.value = "";
  try {
    // 必须透传当前输入框里的 URL：后端 send_notification 在缺省时会回落到
    // 上次 save_config 落盘的 notify_urls，测的就不是用户刚填的内容。
    const urls = configStore.config.notify_urls_text
      .split(/[,，\n\r]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (urls.length === 0) {
      testResult.value = "请先填写通知 URL";
      return;
    }
    const ok = await invoke<boolean>("send_notification", {
      title: "Overwatch Drops Miner",
      body: "这是一条测试通知，收到即表示配置成功",
      notifyUrls: urls,
    });
    testResult.value = ok ? "已发送" : "发送失败，请检查通知 URL";
  } catch (e) {
    testResult.value = `发送失败: ${e}`;
  } finally {
    testing.value = false;
  }
}

interface TaskGroup {
  label: string;
  task_ids: string[];
  active: boolean;
}

const fetchingRoom = ref(false);
const fetchingTasks = ref(false);
const fetchError = ref("");
const saveNotice = ref("");
const saveNoticeError = ref(false);
const showGroupDialog = ref(false);
const pendingGroups = ref<TaskGroup[]>([]);
const selectedGroupIndex = ref(0);

const showBrowserDialog = ref(false);
const availableBrowsers = ref<string[]>([]);
const defaultBrowser = ref("");
const browserLabels = ref<Record<string, string>>({});
const pendingAction = ref<"room" | "task1" | "task2" | null>(null);

const showConfirm = ref(false);
const confirmTitle = ref("");
const confirmMessage = ref("");
const confirmCallback = ref<(() => Promise<void> | void) | null>(null);

onMounted(async () => {
  await configStore.ensureLoaded();
});

/** 真正落盘当前编辑（关窗也会 save，但显式保存让用户不依赖关窗行为） */
async function handleSave() {
  saveNotice.value = "";
  try {
    await configStore.save();
    saveNotice.value = "配置已保存";
    saveNoticeError.value = false;
  } catch (e) {
    saveNotice.value = `保存配置失败: ${e}`;
    saveNoticeError.value = true;
  }
}

async function handleExport() {
  saveNotice.value = "";
  try {
    const filePath = await save({
      defaultPath: "config.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (!filePath) return;
    await invoke("export_config", { path: filePath });
    saveNotice.value = "配置已导出";
    saveNoticeError.value = false;
  } catch (e) {
    saveNotice.value = `导出配置失败: ${e}`;
    saveNoticeError.value = true;
  }
}

async function handleImport() {
  saveNotice.value = "";
  try {
    const filePath = await open({
      multiple: false,
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (!filePath || typeof filePath !== "string") return;
    await invoke("import_config", { path: filePath });
    await configStore.load();
    saveNotice.value = "配置已导入";
    saveNoticeError.value = false;
  } catch (e) {
    saveNotice.value = `导入配置失败: ${e}`;
    saveNoticeError.value = true;
  }
}

/** 取第一个逗号分隔的房间号（对齐后端 parse_room_ids 的 , 与换行拆分语义，
    不能用 /\d+/ 全字段搜第一个数字，否则 "0, 100" 会误判为未填写） */
function firstRoomId(): number {
  const first = configStore.config.rooms_text
    .split(/[,，\n\r]/)
    .map((s) => s.trim())
    .filter(Boolean)[0];
  if (!first || !/^\d+$/.test(first)) return 0;
  const n = parseInt(first, 10);
  return n > 0 ? n : 0;
}

function applyGroup(group: TaskGroup) {
  configStore.config.task_ids_text = group.task_ids.join(",");
}

function applyGroups(groups: TaskGroup[], roomId: number | null | undefined) {
  // 解析失败时不动 rooms_text —— 原实现先覆盖房间号再判空，会在失败路径
  // 也把用户的多房间配置冲掉。
  if (groups.length === 0) {
    fetchError.value = "未解析到掉宝任务分组";
    return;
  }
  if (roomId && roomId > 0) {
    const rooms = configStore.config.rooms_text
      .split(/[,，\n\r]/)
      .map((s) => s.trim())
      .filter(Boolean);
    // 仅当房间号确实不在现有列表中才追加，避免抹掉其余已配房间
    if (!rooms.includes(String(roomId))) {
      configStore.config.rooms_text =
        rooms.length > 0 ? `${rooms.join(",")},${roomId}` : String(roomId);
    }
  }
  if (groups.length === 1) {
    applyGroup(groups[0]);
    return;
  }
  pendingGroups.value = groups;
  selectedGroupIndex.value = Math.max(
    0,
    groups.findIndex((g) => g.active)
  );
  showGroupDialog.value = true;
}

function confirmGroupSelection() {
  const group = pendingGroups.value[selectedGroupIndex.value];
  if (group) applyGroup(group);
  showGroupDialog.value = false;
}

async function handleFetchRoom() {
  if (fetchingRoom.value || fetchingTasks.value) {
    fetchError.value = "已有一个浏览器自动获取任务在进行中，请先完成或关闭主窗口重试。";
    return;
  }
  showConfirmAction(
    "自动获取房间号",
    "即将打开浏览器，请进入目标直播间，程序会从地址栏自动捕获房间号（最长 2 分钟）。",
    // 必须走 showBrowserPicker → executePendingAction → executeFetchRoom，
    // 才会真正 invoke("auto_fetch_room_id")。
    // 原实现只 openUrl 一个**硬编码的第三方 UP 主主页**让用户手动复制：
    // pendingAction 永远到不了 executePendingAction，后端那条活的浏览器
    // 嗅探链路（python_sidecar 的 _run_browser_sniff(kind="room")，约 90 行）
    // 完全是死代码，按钮名与行为也正好相反。
    async () => {
      pendingAction.value = "room";
      await showBrowserPicker();
    }
  );
}

async function handleFetchTaskIdsMode1() {
  if (fetchingTasks.value || fetchingRoom.value) {
    fetchError.value = "已有一个浏览器自动获取任务在进行中，请先完成或关闭主窗口重试。";
    return;
  }
  const roomId = firstRoomId();
  if (!roomId) {
    fetchError.value = "请先填写房间号，或用「自动获取」捕获当前直播间";
    return;
  }
  showConfirmAction(
    "自动获取任务ID（模式1）",
    "即将通过 HTTP 请求获取任务ID，无需浏览器交互。",
    async () => {
      pendingAction.value = "task1";
      await showBrowserPicker();
    }
  );
}

async function handleFetchTaskIdsMode2() {
  if (fetchingTasks.value || fetchingRoom.value) {
    fetchError.value = "已有一个浏览器自动获取任务在进行中，请先完成或关闭主窗口重试。";
    return;
  }
  showConfirmAction(
    "自动获取任务ID（模式2）",
    "即将打开浏览器自动获取任务ID，请打开有当前任务的直播间并等待页面加载完成。",
    async () => {
      pendingAction.value = "task2";
      await showBrowserPicker();
    }
  );
}

function showConfirmAction(
  title: string,
  message: string,
  callback: () => Promise<void> | void,
) {
  confirmTitle.value = title;
  confirmMessage.value = message;
  confirmCallback.value = callback;
  showConfirm.value = true;
}

/** 确认回调可能是 async（如 showBrowserPicker 会抛），必须 await + 捕获，
    否则失败会变成未处理的 Promise 拒绝，UI 上「点了没反应」 */
async function handleConfirm() {
  showConfirm.value = false;
  const cb = confirmCallback.value;
  confirmCallback.value = null;
  if (!cb) return;
  try {
    await cb();
  } catch (e) {
    fetchError.value = `操作失败: ${e}`;
  }
}

function handleCancelConfirm() {
  showConfirm.value = false;
  confirmCallback.value = null;
}

async function showBrowserPicker() {
  try {
    const result = await invoke<{
      available: string[];
      default: string;
      labels: Record<string, string>;
    }>("detect_browsers");
    availableBrowsers.value = result.available;
    defaultBrowser.value = result.default;
    browserLabels.value = result.labels;
    // 0 个浏览器必须与 1 个区分处理：原实现把两者合并，
    // 空数组时 default === ""，仍会启动一个最长 120 秒的嗅探会话，
    // 用户只看到转圈 2 分钟后一句超时，真正的错误信息永不出现。
    if (result.available.length === 0) {
      pendingAction.value = null;
      fetchError.value = "未检测到受支持的浏览器（Edge / Chrome / Firefox），请手动填写";
      return;
    }
    if (result.available.length === 1) {
      await executePendingAction(result.default);
      return;
    }
    showBrowserDialog.value = true;
  } catch (e) {
    pendingAction.value = null;
    fetchError.value = `检测浏览器失败: ${e}`;
  }
}

async function executePendingAction(browser: string) {
  const action = pendingAction.value;
  pendingAction.value = null;
  if (action === "room") {
    await executeFetchRoom(browser);
  } else if (action === "task1") {
    await executeFetchTaskIdsMode1(browser);
  } else if (action === "task2") {
    await executeFetchTaskIdsMode2(browser);
  }
}

async function executeFetchRoom(browser: string) {
  fetchingRoom.value = true;
  fetchError.value = "";
  try {
    const result = await invoke<{ room_id: number }>("auto_fetch_room_id", { browser });
    // 追加而非整体覆盖：自动捕获到的只是「当前浏览器所在的那个直播间」，
    // 整体覆盖会抹掉用户已配置的其他房间。
    const captured = String(result.room_id);
    const rooms = configStore.config.rooms_text
      .split(/[,，\n\r]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!rooms.includes(captured)) {
      configStore.config.rooms_text =
        rooms.length > 0 ? `${rooms.join(",")},${captured}` : captured;
    }
  } catch (e) {
    fetchError.value = `自动获取房间号失败: ${e}`;
  } finally {
    fetchingRoom.value = false;
  }
}

async function executeFetchTaskIdsMode1(browser: string) {
  fetchingTasks.value = true;
  fetchError.value = "";
  try {
    const result = await invoke<{ room_id: number; groups: TaskGroup[] }>(
      "auto_fetch_task_ids",
      { roomId: firstRoomId(), browser }
    );
    applyGroups(result.groups, result.room_id);
  } catch (e) {
    fetchError.value = `自动获取模式1失败: ${e}`;
  } finally {
    fetchingTasks.value = false;
  }
}

async function executeFetchTaskIdsMode2(browser: string) {
  fetchingTasks.value = true;
  fetchError.value = "";
  try {
    const result = await invoke<{
      room_id: number | null;
      groups: TaskGroup[];
    }>("auto_fetch_task_ids_mode2", { roomId: firstRoomId() || null, browser });
    applyGroups(result.groups, result.room_id);
  } catch (e) {
    fetchError.value = `自动获取模式2失败: ${e}`;
  } finally {
    fetchingTasks.value = false;
  }
}

function selectBrowser(browser: string) {
  showBrowserDialog.value = false;
  executePendingAction(browser);
}

function cancelBrowserPicker() {
  showBrowserDialog.value = false;
  pendingAction.value = null;
}
</script>

<template>
  <!-- 对齐旧版 main_layout.py:122-205：无卡头、单列行式（标签 + 输入 + 行内按钮），
       按钮行只保留加载/保存（启动/停止由账号行内按钮承担），全局进度条收于卡底 -->
  <Card class="card-hover">
    <CardContent class="px-[18px] py-[14px]">
      <div class="mb-2.5 flex items-center gap-2">
        <Label for="rooms" class="min-w-[72px] shrink-0 text-sm">房间号</Label>
        <Input
          id="rooms"
          v-model="configStore.config.rooms_text"
          placeholder="必填: 直播间号，多个用逗号分隔"
          class="h-8 min-w-0 flex-1 text-sm"
        />
        <Button
          size="sm"
          class="h-8 min-w-[90px] shrink-0 text-sm"
          :disabled="fetchingRoom"
          @click="handleFetchRoom"
        >
          {{ fetchingRoom ? "捕获中..." : "自动获取" }}
        </Button>
      </div>

      <div class="mb-2.5 flex items-center gap-2">
        <Label for="taskIds" class="min-w-[72px] shrink-0 text-sm">任务 ID</Label>
        <Input
          id="taskIds"
          v-model="configStore.config.task_ids_text"
          placeholder="可留空: 可用浏览器嗅探自动获取（模式1需先有房间号）"
          class="h-8 min-w-0 flex-1 text-sm"
        />
        <Button
          size="sm"
          class="h-8 min-w-[90px] shrink-0 text-sm"
          :disabled="fetchingTasks || fetchingRoom"
          :title="fetchingRoom ? '任务 ID 捕获进行中，请稍候' : undefined"
          @click="handleFetchTaskIdsMode1"
        >
          {{ fetchingTasks && pendingAction === "task1" ? "捕获中..." : "自动获取模式1" }}
        </Button>
        <Button
          size="sm"
          class="h-8 min-w-[90px] shrink-0 text-sm"
          :disabled="fetchingTasks || fetchingRoom"
          :title="fetchingRoom ? '任务 ID 捕获进行中，请稍候' : undefined"
          @click="handleFetchTaskIdsMode2"
        >
          {{ fetchingTasks ? "捕获中..." : "自动获取模式2" }}
        </Button>
      </div>

      <div class="mb-2.5 flex items-center gap-2">
        <Label for="notifyUrls" class="min-w-[72px] shrink-0 text-sm">通知 URL</Label>
        <Input
          id="notifyUrls"
          v-model="configStore.config.notify_urls_text"
          placeholder="可留空: 通知 URL，如 gotify://host/token"
          class="h-8 min-w-0 flex-1 text-sm"
        />
        <Button
          size="sm"
          variant="outline"
          class="h-8 min-w-[90px] shrink-0 text-sm"
          :disabled="testing"
          @click="handleTest"
        >
          {{ testing ? "发送中..." : "测试通知" }}
        </Button>
      </div>

      <!-- 数值行 + 复选框（对齐旧版 num_row：spacing 12 + stretch） -->
      <div class="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div class="flex items-center gap-1.5">
          <Label for="threads" class="whitespace-nowrap text-sm">线程数</Label>
          <Input
            id="threads"
            v-model="configStore.config.thread_count_text"
            type="number"
            min="1"
            max="256"
            class="h-8 w-[76px] text-sm"
          />
        </div>
        <div class="flex items-center gap-1.5">
          <Label for="reconnect" class="whitespace-nowrap text-sm">重连延迟(s)</Label>
          <Input
            id="reconnect"
            v-model="configStore.config.reconnect_delay_text"
            type="number"
            min="1"
            max="3600"
            class="h-8 w-[76px] text-sm"
          />
        </div>
        <div class="flex items-center gap-1.5">
          <Label for="interval" class="whitespace-nowrap text-sm">任务查询间隔(s)</Label>
          <Input
            id="interval"
            v-model="configStore.config.task_query_interval_text"
            type="number"
            min="10"
            max="3600"
            class="h-8 w-[76px] text-sm"
          />
        </div>
        <div class="flex items-center gap-1.5">
          <Checkbox
            id="cfg-verbose"
            :model-value="configStore.config.verbose"
            aria-label="详细日志"
            @update:model-value="configStore.config.verbose = $event === 'indeterminate' ? true : $event"
          />
          <Label for="cfg-verbose" class="cursor-pointer text-sm">详细日志</Label>
        </div>
        <div class="flex items-center gap-1.5">
          <Checkbox
            id="cfg-disable-task-notify"
            :model-value="disableTaskNotify"
            aria-label="禁用任务完成通知"
            @update:model-value="disableTaskNotify = $event === 'indeterminate' ? true : $event"
          />
          <Label for="cfg-disable-task-notify" class="cursor-pointer text-sm">禁用任务完成通知</Label>
        </div>
      </div>

      <!-- 操作按钮：「保存配置」= 落盘当前编辑（真正持久化）；「导入/导出」= 文件读写 -->
      <div class="mb-2.5 flex items-center gap-2">
        <Button size="sm" class="h-8 text-sm" @click="handleSave">
          保存配置
        </Button>
        <Button size="sm" variant="outline" class="h-8 text-sm" @click="handleImport">
          导入配置
        </Button>
        <Button size="sm" variant="outline" class="h-8 text-sm" @click="handleExport">
          导出配置
        </Button>
      </div>

      <p
        v-if="fetchError"
        class="mb-1.5 break-all text-xs text-signal-danger"
      >
        {{ fetchError }}
      </p>
      <p
        v-if="saveNotice"
        class="mb-1.5 break-all text-xs"
        :class="saveNoticeError ? 'text-signal-danger' : 'text-signal-success'"
      >
        {{ saveNotice }}
      </p>
      <p
        v-if="testResult"
        class="mb-1.5 break-all text-xs"
        :class="testResult === '已发送' ? 'text-signal-success' : 'text-signal-danger'"
      >
        {{ testResult }}
      </p>
      <p class="text-xs text-muted-foreground">
        模式1：纯 HTTP 抓取直播间页面（需先填房间号）；模式2：浏览器嗅探（自动同时获取房间号）
      </p>

      <!-- 运行中全局 indeterminate 进度动画（旧版 main_layout.py:198-205，初始隐藏） -->
      <div
        v-if="anyRunning"
        class="relative mt-2.5 h-1.5 w-full overflow-hidden rounded bg-secondary"
        role="progressbar"
        aria-label="账号运行中"
      >
        <div class="progress-indeterminate absolute h-full w-1/3 bg-primary" />
      </div>
    </CardContent>
  </Card>

    <!-- 任务组选择（多个分组时弹出，对齐原 QInputDialog.getItem） -->
    <Dialog v-model:open="showGroupDialog">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>选择掉宝任务组</DialogTitle>
          <DialogDescription>
            检测到多个按日期分组的掉宝任务，请选择要填入的一组
          </DialogDescription>
        </DialogHeader>
        <fieldset class="space-y-2 py-2">
          <legend class="sr-only">按日期分组的掉宝任务</legend>
          <label
            v-for="(group, index) in pendingGroups"
            :key="`${group.label}-${group.task_ids[0] ?? index}`"
            class="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm"
            :class="
              index === selectedGroupIndex
                ? 'border-primary bg-accent/60'
                : 'border-border hover:bg-accent/50'
            "
          >
            <input
              v-model="selectedGroupIndex"
              type="radio"
              name="task-group"
              :value="index"
              class="accent-primary"
            />
            <span>{{ group.label }}（{{ group.task_ids.length }} 个任务）</span>
          </label>
        </fieldset>
        <div class="flex justify-end gap-2">
          <Button variant="outline" size="sm" @click="showGroupDialog = false">
            取消
          </Button>
          <Button size="sm" @click="confirmGroupSelection">
            填入选中分组
          </Button>
        </div>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="showBrowserDialog">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>选择浏览器</DialogTitle>
          <DialogDescription>
            检测到多个可用浏览器，请选择用于自动获取的浏览器
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-2 py-2">
          <button
            v-for="browser in availableBrowsers"
            :key="browser"
            class="flex w-full items-center gap-2 rounded-md border p-2 text-sm text-left"
            :class="
              browser === defaultBrowser
                ? 'border-primary bg-accent/60'
                : 'border-border hover:bg-accent/50'
            "
            @click="selectBrowser(browser)"
          >
            <span>{{ browserLabels[browser] || browser }}</span>
            <span v-if="browser === defaultBrowser" class="text-xs text-muted-foreground">
              (默认)
            </span>
          </button>
        </div>
        <div class="flex justify-end gap-2">
          <Button variant="outline" size="sm" @click="cancelBrowserPicker">
            取消
          </Button>
        </div>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="showConfirm">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{{ confirmTitle }}</DialogTitle>
          <DialogDescription>{{ confirmMessage }}</DialogDescription>
        </DialogHeader>
        <div class="flex justify-end gap-2">
          <Button variant="outline" size="sm" @click="handleCancelConfirm">
            取消
          </Button>
          <Button size="sm" @click="handleConfirm">
            确认
          </Button>
        </div>
      </DialogContent>
    </Dialog>
</template>
