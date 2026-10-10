<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { save, open } from "@tauri-apps/plugin-dialog";
import { LoaderCircle } from "lucide-vue-next";
import { useConfigStore, TaskIdsAlteredError } from "@/stores/config";
import { useAccountsStore } from "@/stores/accounts";
import { useTimedNotice } from "@/lib/notice";
import { formatIpcError } from "@/lib/ipc-error";
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
/** 「测试通知」的结果反馈位。3 秒自动消失，见 useTimedNotice 的注释。 */
const {
  text: testResult,
  show: showTestResult,
  clear: clearTestResult,
} = useTimedNotice();

/** 详细日志开关的即时生效失败原因。复选框下方就地展示，
    不用 saveNotice —— 那是「保存配置」的反馈位，两件事混在一起会互相覆盖。 */
const {
  text: verboseError,
  show: showVerboseError,
  clear: clearVerboseError,
} = useTimedNotice();

/** 勾选即时生效。失败必须让用户看见：复选框已经翻了（看起来已生效），
    但日志级别没变，用户会以为程序有 bug 而不会怀疑刚才那次点击。 */
async function handleToggleVerbose(next: boolean) {
  clearVerboseError();
  try {
    await configStore.setVerbose(next);
  } catch (e) {
    showVerboseError(formatIpcError(e, "详细日志切换失败"), true);
  }
}

function onVerboseModelValue(v: boolean | "indeterminate") {
  void handleToggleVerbose(v === "indeterminate" ? true : v);
}

async function handleTest() {
  testing.value = true;
  clearTestResult();
  try {
    // 必须透传当前输入框里的 URL：后端 send_notification 在缺省时会回落到
    // 上次 save_config 落盘的 notify_urls，测的就不是用户刚填的内容。
    const urls = configStore.config.notify_urls_text
      .split(/[,，\n\r]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (urls.length === 0) {
      showTestResult("请先填写通知 URL", true);
      return;
    }
    const ok = await invoke<boolean>("send_notification", {
      title: "Overwatch Drops Miner",
      body: "这是一条测试通知，收到即表示配置成功",
      notifyUrls: urls,
    });
    // 成败由文案本身决定（「已发送」是唯一的成功文案），
    // 所以颜色仍按文案判断，不额外维护一个 isError
    showTestResult(ok ? "已发送" : "发送失败，请检查通知 URL", !ok);
  } catch (e) {
    showTestResult(formatIpcError(e, "发送失败"), true);
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
const {
  text: fetchError,
  show: showFetchError,
  clear: clearFetchError,
} = useTimedNotice();
/** 保存 / 导入 / 导出三个操作共用一条反馈位。
    isError 除了决定配色，还区分「已落盘但内容变了」这种中间态。 */
const {
  text: saveNotice,
  isError: saveNoticeError,
  show: showSaveNotice,
  clear: clearSaveNotice,
} = useTimedNotice();
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

/** 重试配置加载。load() 失败会 throw（config.ts 的 catch 分支里 rethrow），
    不接住会变成未处理的 Promise 拒绝 —— 按钮看起来「点了没反应」。 */
async function retryLoadConfig() {
  try {
    await configStore.load();
  } catch {
    /* 失败原因已由 store 写进 loadError 并显示在上方，这里只需吞掉拒绝 */
  }
}

/** 真正落盘当前编辑（关窗也会 save，但显式保存让用户不依赖关窗行为） */
async function handleSave() {
  clearSaveNotice();
  try {
    await configStore.save();
    showSaveNotice("配置已保存", false);
  } catch (e) {
    // 任务 ID 集合被后端改写属于「已落盘但内容变了」，不是保存失败：
    // 措辞必须区分，否则用户会反复点保存试图「修好」一个并不存在的问题。
    if (e instanceof TaskIdsAlteredError) {
      showSaveNotice(
        "配置已保存，但任务 ID 与提交的不一致，已按后端实际落盘的值填回：" +
        `${e.saved || "（空）"}`,
        true
      );
      return;
    }
    showSaveNotice(formatIpcError(e), true);
  }
}

async function handleExport() {
  clearSaveNotice();
  try {
    const filePath = await save({
      defaultPath: "config.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (!filePath) return;
    await invoke("export_config", { path: filePath });
    showSaveNotice("配置已导出", false);
  } catch (e) {
    showSaveNotice(formatIpcError(e, "导出配置失败"), true);
  }
}

async function handleImport() {
  clearSaveNotice();
  try {
    const filePath = await open({
      multiple: false,
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (!filePath || typeof filePath !== "string") return;
    await invoke("import_config", { path: filePath });
    await configStore.load();
    showSaveNotice("配置已导入", false);
  } catch (e) {
    showSaveNotice(formatIpcError(e, "导入配置失败"), true);
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
    showFetchError("未解析到掉宝任务分组", true);
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
    showFetchError("已有一个浏览器自动获取任务在进行中，请先完成或关闭主窗口重试。", true);
    return;
  }
  showConfirmAction(
    "自动跳转房间号",
    "即将打开浏览器到「守望先锋电竞」UP 主主页，请点进任意目标直播间，程序会从地址栏自动捕获房间号（最长 2 分钟）。",
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
    showFetchError("已有一个浏览器自动获取任务在进行中，请先完成或关闭主窗口重试。", true);
    return;
  }
  const roomId = firstRoomId();
  if (!roomId) {
    showFetchError("请先填写房间号，或用「自动获取」捕获当前直播间", true);
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
    showFetchError("已有一个浏览器自动获取任务在进行中，请先完成或关闭主窗口重试。", true);
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
    showFetchError(formatIpcError(e, "操作失败"), true);
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
      showFetchError("未检测到受支持的浏览器（Edge / Chrome / Firefox），请手动填写", true);
      return;
    }
    if (result.available.length === 1) {
      await executePendingAction(result.default);
      return;
    }
    showBrowserDialog.value = true;
  } catch (e) {
    pendingAction.value = null;
    showFetchError(formatIpcError(e, "检测浏览器失败"), true);
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
  clearFetchError();
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
    showFetchError(formatIpcError(e, "自动跳转房间号失败"), true);
  } finally {
    fetchingRoom.value = false;
  }
}

async function executeFetchTaskIdsMode1(browser: string) {
  fetchingTasks.value = true;
  clearFetchError();
  try {
    const result = await invoke<{ room_id: number; groups: TaskGroup[] }>(
      "auto_fetch_task_ids",
      { roomId: firstRoomId(), browser }
    );
    applyGroups(result.groups, result.room_id);
  } catch (e) {
    showFetchError(formatIpcError(e, "自动获取模式1失败"), true);
  } finally {
    fetchingTasks.value = false;
  }
}

async function executeFetchTaskIdsMode2(browser: string) {
  fetchingTasks.value = true;
  clearFetchError();
  try {
    const result = await invoke<{
      room_id: number | null;
      groups: TaskGroup[];
    }>("auto_fetch_task_ids_mode2", { roomId: firstRoomId() || null, browser });
    applyGroups(result.groups, result.room_id);
  } catch (e) {
    showFetchError(formatIpcError(e, "自动获取模式2失败"), true);
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
  <!-- 无卡头、单列行式（标签 + 输入 + 行内按钮）：
       按钮行只保留加载/保存（启动/停止由账号行内按钮承担），全局进度条收于卡底。

       内边距统一到 4px 网格（px-4 / py-4，均 16px）：
       原先三张卡写的是 18px 横向 + 14px 纵向的任意值 —— 18px 在 Tailwind
       刻度里没有对应档位，14px 虽是 3.5 档但同属 .5 半档、不在 4px 网格上。
       统一为 16px 后三张卡四边一致。

       **注释里刻意不复写旧类名**：Tailwind v4 按**源码原始文本**扫描，
       注释里出现的类名会被当真生成进产物 CSS ——
       本项目实测过：一条 HTML 注释里的任意值类名让产物多出一条死规则。
       这里一律用「18px 横向」这样的自然语言描述旧值，避免污染产物。

       **纵向改 16px 会让内容总高 +8px**（本卡 +4、挂宝卡 +2、日志卡 +2），
       因此最小窗口高度同步从 860 抬到 868（见 App.vue 的 MIN_WINDOW_HEIGHT
       与 tauri.conf.json 的 minHeight，三处必须同源）。
       868 的来历：裸下限 853 + 8 = 861，保留原设计同样的 7px 余量
       （用于吸收 3 秒行内提示带来的瞬时增高），861 + 7 = 868，
       且 868 是 4 的倍数。 -->
  <Card data-nav-region="config" data-nav-order="3" class="card-hover">
    <CardContent class="space-y-3.5 px-4 py-4">
      <!-- 加载失败：必须在卡内就地告知并给重试入口。
           原先 loadError 只有 store 在写、没有任何组件读，失败终点是
           App.vue 的 runStep 里一句 console.error —— 用户看到的是
           config.ts 里那份默认值（房间号 23612045、线程 60、间隔 30），
           一份「看起来已经配好了」的表单，会以为自己的配置被重置。
           与账号栏的错误态（AccountList 的 role="alert" + 重试）保持同构。 -->
      <p
        v-if="configStore.loadError"
        class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-signal-danger/10 px-2.5 py-1.5 text-xs text-signal-danger"
        role="alert"
      >
        <!-- 不要再拼「配置加载失败：」前缀：store 侧已经用
             formatIpcError(e, "加载配置失败") 带上了它，这里再加一次会渲染成
             「配置加载失败：加载配置失败：后台服务响应超时，请稍后重试」。
             与保存路径同构 —— config.ts 抛出的串已带前缀，调用方一律不再补。 -->
        <span class="break-all">{{ configStore.loadError }}</span>
        <button
          type="button"
          class="shrink-0 underline underline-offset-2 hover:text-foreground
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="retryLoadConfig"
        >
          重试
        </button>
      </p>

      <!-- 加载中：整块表单换成占位态。
           不是装饰性骨架屏，是**功能性互斥** —— 表单所有输入框都直接
           双向绑定 store（v-model="configStore.config.xxx"），而 load()
           成功时执行 config.value = next 整体替换。窗口在
           restoreWindowGeometry 的 2~4 次轻量 IPC 后就显示，而配置加载
           排在 4 个 runStep 的最后（前面还有两次 initListeners 与一次
           完整的 fetchAccounts 往返）—— 这段时间里用户敲进去的字会被
           整片覆盖，且没有任何提示。用 v-if 把表单换掉即可关掉竞争窗口，
           比事后做「脏字段合并」可靠得多。 -->
      <div
        v-if="configStore.loading"
        class="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground"
        role="status"
        aria-live="polite"
      >
        <LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />
        正在加载配置…
      </div>

      <template v-else>
        <!-- 分组一：连接与任务
             标签列宽度取 style.css 的 --cfg-label-w 而不是各写各的字面量：
             本组三行与下方运行参数三行必须共用同一个左边缘，
             否则「线程数」（3 字）会比「查询间隔(s)」（8 字）缩进 40px。
             minmax(0,1fr) 给输入框，auto 给行内按钮组：
             按钮组的 min-content 必须原样保留，列宽才不会被压到内容以下。 -->
        <fieldset class="space-y-2">
          <legend class="sr-only">连接与任务</legend>
          <div class="grid grid-cols-[var(--cfg-label-w)_minmax(0,1fr)_auto] items-center gap-2">
            <Label for="rooms" class="text-left text-sm">房间号</Label>
            <Input
              id="rooms"
              v-model="configStore.config.rooms_text"
              placeholder="必填: 直播间号，多个用逗号分隔"
              class="h-8 min-w-0 text-sm"
            />
            <Button
              size="sm"
              variant="outline"
              class="h-8 min-w-[88px] text-sm"
              :disabled="fetchingRoom"
              @click="handleFetchRoom"
            >
              {{ fetchingRoom ? "跳转中..." : "自动跳转" }}
            </Button>
          </div>

          <div class="grid grid-cols-[var(--cfg-label-w)_minmax(0,1fr)_auto] items-center gap-2">
            <Label for="taskIds" class="text-left text-sm">任务 ID</Label>
            <!-- 占位文案必须按「输入框在最窄可用宽度下仍能完整显示」来写，
                 而不是把想说的话都塞进去。
                 本行的宽度是 `74(标签) + 8 + input + 8 + 241(两个「自动获取模式X」按钮)`
                 切出来的，input 在最小窗口 1030、侧栏拖到最宽 420 时只剩约 209px
                 （扣掉 input 自身 26px 内边距与边框，可用文字宽约 183px）。
                 原文案「可留空: 可用浏览器嗅探自动获取（模式1需先有房间号）」约需 380px，
                 括号部分永远被截掉 —— 用户看到的是一句残缺的话。
                 现在这句约 206px，在默认侧栏 240（input 约 389px）下完整显示。
                 被删掉的「模式1 需先有房间号」并没有丢：本卡片底部的说明行写着
                 「模式1：纯 HTTP 抓取直播间页面（需先填房间号）」，输入框的
                 title 也带完整说明，两处都不遮挡任何可见文字。 -->
            <Input
              id="taskIds"
              v-model="configStore.config.task_ids_text"
              placeholder="可留空: 可用浏览器嗅探自动获取"
              title="可留空。点「自动获取模式1」用纯 HTTP 抓取直播间页面（需先填房间号）；点「自动获取模式2」用浏览器嗅探，并同时自动获取房间号。"
              class="h-8 min-w-0 text-sm"
            />
            <div class="flex gap-1.5">
              <Button
                size="sm"
                variant="outline"
                class="h-8 min-w-[92px] text-sm"
                :disabled="fetchingTasks || fetchingRoom"
                :title="fetchingRoom ? '任务 ID 捕获进行中，请稍候' : undefined"
                @click="handleFetchTaskIdsMode1"
              >
                {{ fetchingTasks && pendingAction === "task1" ? "捕获中..." : "自动获取模式1" }}
              </Button>
              <Button
                size="sm"
                variant="outline"
                class="h-8 min-w-[92px] text-sm"
                :disabled="fetchingTasks || fetchingRoom"
                :title="fetchingRoom ? '任务 ID 捕获进行中，请稍候' : undefined"
                @click="handleFetchTaskIdsMode2"
              >
                {{ fetchingTasks ? "捕获中..." : "自动获取模式2" }}
              </Button>
            </div>
          </div>

          <div class="grid grid-cols-[var(--cfg-label-w)_minmax(0,1fr)_auto] items-center gap-2">
            <Label for="notifyUrls" class="text-left text-sm">通知 URL</Label>
            <Input
              id="notifyUrls"
              v-model="configStore.config.notify_urls_text"
              placeholder="可留空: 通知 URL，如 gotify://host/token"
              class="h-8 min-w-0 text-sm"
            />
            <Button
              size="sm"
              variant="outline"
              class="h-8 min-w-[88px] text-sm"
              :disabled="testing"
              @click="handleTest"
            >
              {{ testing ? "发送中..." : "测试通知" }}
            </Button>
          </div>
        </fieldset>

        <!-- 分组二：运行参数。三块在同一行里做贴左 / 居中 / 贴右分布，
               列模板是 repeat(3, minmax(160px, 1fr)) 而不是「三列等宽」写法。

               为什么不能用三列等宽：它展开为
               `repeat(3, minmax(0, 1fr))`，下限是 0 —— 列宽可以缩到比内容还窄；
               而块内的标签 `w-[var(--cfg-label-w)] shrink-0` 与输入框
               `w-[68px] shrink-0` 都不允许缩，于是内容溢出各自的列、
               往右压到相邻列上，表现为「按钮重叠」。
               写成 minmax(160px, 1fr)（160 = 74 + 8 + 68，即
               --cfg-label-w + gap + 输入框宽）后，列宽永远 ≥ 内容宽，窄窗口下的表现从
               「重叠」变成「整卡溢出」——后者由最小窗口尺寸兜住，
               前者无论窗口多宽都会出现。

               （本条注释刻意不写那个旧类名本身：Tailwind v4 按源码原始文本
               扫描，注释里出现的类名会被当真生成进产物 CSS ——
               本项目已实测确证产物里真的会多出死规则。）

               标签列同样取 --cfg-label-w 并全部左对齐：三块与上方三行的
               标签、输入框左边缘完全齐平。 -->
        <fieldset class="space-y-2">
          <legend class="sr-only">运行参数</legend>
          <div class="grid grid-cols-[repeat(3,minmax(160px,1fr))] items-center">
            <div class="flex items-center justify-self-start gap-2">
              <Label
                for="threads"
                class="w-[var(--cfg-label-w)] shrink-0 text-left text-sm"
              >线程数</Label>
              <Input
                id="threads"
                v-model="configStore.config.thread_count_text"
                type="number"
                min="1"
                max="256"
                class="h-8 w-[68px] shrink-0 text-sm"
              />
            </div>
            <div class="flex items-center justify-self-center gap-2">
              <Label
                for="reconnect"
                class="w-[var(--cfg-label-w)] shrink-0 text-left text-sm"
              >重连延迟(s)</Label>
              <Input
                id="reconnect"
                v-model="configStore.config.reconnect_delay_text"
                type="number"
                min="1"
                max="3600"
                class="h-8 w-[68px] shrink-0 text-sm"
              />
            </div>
            <div class="flex items-center justify-self-end gap-2">
              <Label
                for="interval"
                class="w-[var(--cfg-label-w)] shrink-0 text-left text-sm"
              >查询间隔(s)</Label>
              <Input
                id="interval"
                v-model="configStore.config.task_query_interval_text"
                type="number"
                min="10"
                max="3600"
                class="h-8 w-[68px] shrink-0 text-sm"
              />
            </div>
          </div>

          <!-- 复选框单独一行：它们是行为开关而非数值参数，混在数值里会让人
               误以为与线程数等同属一组可调参数 -->
          <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 pt-0.5">
            <div class="flex items-center gap-1.5">
              <Checkbox
                id="cfg-verbose"
                :model-value="configStore.config.verbose"
                aria-label="详细日志"
                @update:model-value="onVerboseModelValue"
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
              <Label for="cfg-disable-task-notify" class="cursor-pointer text-sm">
                禁用任务完成通知
              </Label>
            </div>
          </div>
          <p
            v-if="verboseError"
            class="break-all text-xs text-signal-danger"
            role="alert"
          >
            {{ verboseError }}
          </p>
        </fieldset>

        <!-- 操作按钮 -->
        <div class="flex items-center gap-2">
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

        <!-- 提示与错误。role="alert" 不能省：自动获取失败是异步发生的，
             没有它屏幕阅读器不会播报，用户只会看到配置悄悄没填上 -->
        <p
          v-if="fetchError"
          class="break-all rounded-md bg-signal-danger/10 px-2.5 py-1.5 text-xs text-signal-danger"
          role="alert"
        >
          {{ fetchError }}
        </p>
        <p
          v-if="saveNotice"
          class="break-all rounded-md px-2.5 py-1.5 text-xs"
          :class="saveNoticeError ? 'bg-signal-danger/10 text-signal-danger' : 'bg-signal-success/10 text-signal-success'"
          role="status"
        >
          {{ saveNotice }}
        </p>
        <p
          v-if="testResult"
          class="break-all rounded-md px-2.5 py-1.5 text-xs"
          :class="testResult === '已发送' ? 'bg-signal-success/10 text-signal-success' : 'bg-signal-danger/10 text-signal-danger'"
          role="status"
        >
          {{ testResult }}
        </p>
        <p class="text-xs leading-relaxed text-muted-foreground">
          模式1：纯 HTTP 抓取直播间页面（需先填房间号）；模式2：浏览器嗅探（自动同时获取房间号）
        </p>

        <!-- 运行中全局 indeterminate 进度动画，初始隐藏 -->
        <div
          v-if="anyRunning"
          class="relative mt-2.5 h-1.5 w-full overflow-hidden rounded bg-secondary"
          role="progressbar"
          aria-label="账号运行中"
        >
          <div class="progress-indeterminate absolute h-full w-1/3 bg-primary" />
        </div>
      </template>
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
          <!-- focus-visible 不可省：这些是裸 button（未走 ui/button），全项目唯一
               一处漏掉焦点环的可聚焦元素，键盘 Tab 过来焦点完全不可见。
               focus-visible 而非 focus：鼠标点击不显示焦点环。 -->
          <button
            v-for="browser in availableBrowsers"
            :key="browser"
            type="button"
            class="flex w-full items-center gap-2 rounded-md border p-2 text-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
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
