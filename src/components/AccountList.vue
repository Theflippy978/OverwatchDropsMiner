<script setup lang="ts">
import { ref, nextTick, onUnmounted } from "vue";
import { storeToRefs } from "pinia";
import { useSortable } from "@vueuse/integrations/useSortable";
import { useAccountsStore } from "@/stores/accounts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { useTimedNotice } from "@/lib/notice";
import { formatIpcError } from "@/lib/ipc-error";
import ConfirmDialog from "@/components/ConfirmDialog.vue";

const accountsStore = useAccountsStore();

const props = defineProps<{
  selectedId: string | null;
}>();

const emit = defineEmits<{
  select: [accountId: string];
  "qr-login": [];
}>();

const showAddDialog = ref(false);
const newCookie = ref("");
const adding = ref(false);
const capturing = ref(false);

const showRenameDialog = ref(false);
const renameTargetId = ref("");
const renameValue = ref("");
const renaming = ref(false);
/** 重命名失败的原因。必须留在 Dialog 内部：Dialog 打开时全屏遮罩会吃掉
    指针事件，页面底部的错误条既看不见也点不到，用户只会认为程序卡死。
    同时保证失败后对话框不自动关闭——自动关闭会让用户丢掉刚输入的内容。 */
const renameError = ref("");

const showCaptureConfirm = ref(false);
const captureError = ref("");

const showRemoveConfirm = ref(false);
const removeTargetId = ref("");
const removeTargetRemark = ref("");
const removing = ref(false);
/** 正在进行中的操作，元素形如 `${accountId}:start` / `${accountId}:stop`。
    用 Set 而不是单个字符串：禁用范围收窄到「当前操作行」之后，
    单值会被后一次操作覆盖掉前一个（同时启停两个账号时按错的行禁用）。
    Vue 3 的 ref 会把 Set 变成响应式集合，add/delete 本身即触发更新。 */
const pendingActions = ref(new Set<string>());

/** 该账号是否有操作在途。禁用只针对这一个账号，
    早期实现是 `pendingAction !== ''` —— 一行在操作，全部账号行一起变灰。 */
function isPending(accountId: string): boolean {
  return (
    pendingActions.value.has(`${accountId}:start`) ||
    pendingActions.value.has(`${accountId}:stop`)
  );
}

/** 页内错误提示，只用于不涉及弹窗的操作（启动/停止），3 秒自动消失。
    凡是在 Dialog / ConfirmDialog 内失败的操作，提示必须放进那个框里**且
    绝不能自动消失**：弹窗打开时全屏遮罩会吃掉指针事件并盖住页面上的任何提示，
    用户既看不到错误也点不掉弹窗，只会认为程序卡死。
    （`addError` / `renameError` / `captureError` / `removeError` 四处保持常驻。） */
const {
  text: actionError,
  show: showActionError,
  clear: clearActionError,
} = useTimedNotice();
const addError = ref("");
const removeError = ref("");

function openRenameDialog(accountId: string, currentRemark: string) {
  renameTargetId.value = accountId;
  renameValue.value = currentRemark;
  renameError.value = "";
  showRenameDialog.value = true;
}

async function handleRenameAccount() {
  const remark = renameValue.value.trim();
  if (!remark || !renameTargetId.value) return;
  renaming.value = true;
  renameError.value = "";
  try {
    await accountsStore.renameAccount(renameTargetId.value, remark);
    showRenameDialog.value = false;
  } catch (e) {
    renameError.value = formatIpcError(e);
  } finally {
    renaming.value = false;
  }
}

async function handleAddAccount() {
  if (!newCookie.value.trim()) return;
  adding.value = true;
  addError.value = "";
  try {
    const account = await accountsStore.addAccount(newCookie.value.trim());
    newCookie.value = "";
    showAddDialog.value = false;
    if (account) emit("select", account.id);
  } catch (e) {
    addError.value = formatIpcError(e, "添加账号失败");
  } finally {
    adding.value = false;
  }
}

function handleRemoveAccount(accountId: string) {
  const account = accountsStore.accounts.find((a) => a.id === accountId);
  removeTargetId.value = accountId;
  removeTargetRemark.value = account?.remark || accountId.slice(0, 8);
  removeError.value = "";
  showRemoveConfirm.value = true;
}

async function confirmRemoveAccount() {
  if (!removeTargetId.value) return;
  removing.value = true;
  removeError.value = "";
  try {
    await accountsStore.removeAccount(removeTargetId.value);
    showRemoveConfirm.value = false;
    removeTargetId.value = "";
  } catch (e) {
    // 失败时保留 removeTargetId：清空它会让框内的错误提示无法重试，
    // 用户只能关掉重来。
    removeError.value = formatIpcError(e, "删除账号失败");
  } finally {
    removing.value = false;
  }
}

function cancelRemoveAccount() {
  showRemoveConfirm.value = false;
  removeTargetId.value = "";
}

/** 启停的等待期只靠 disabled 表达，按钮文案必须恒为「启动」/「停止」。
    早前会把文案换成「启动中...」「停止中...」，而按钮只有 px-3 没有固定宽，
    文案一变宽就变 —— 整行跟着左右抖，在多账号列表里尤其明显。
    换成图标（旋转 spinner）能兼顾两者，但那样 disabled 的半透明会把图标一起
    淡掉，等待感反而更弱；文案恒定是最省事也最不容易出错的形态。 */
async function handleStart(accountId: string) {
  if (isPending(accountId)) return;
  const token = `${accountId}:start`;
  pendingActions.value.add(token);
  clearActionError();
  try {
    await accountsStore.startMiner(accountId);
    // 启动后自动选中该账号：用户点「启动」的意图就是「我要看这个账号」，
    // 不自动选中会让他再点一次账号行，而进度卡还停在别的账号上。
    emit("select", accountId);
  } catch (e) {
    showActionError(formatIpcError(e, "启动失败"), true);
  } finally {
    pendingActions.value.delete(token);
  }
}

async function handleStop(accountId: string) {
  if (isPending(accountId)) return;
  const token = `${accountId}:stop`;
  pendingActions.value.add(token);
  clearActionError();
  try {
    await accountsStore.stopMiner(accountId);
  } catch (e) {
    showActionError(formatIpcError(e, "停止失败"), true);
  } finally {
    pendingActions.value.delete(token);
  }
}

function handleCaptureCookie() {
  captureError.value = "";
  showCaptureConfirm.value = true;
}

async function confirmCaptureCookie() {
  if (capturing.value) return;
  captureError.value = "";
  capturing.value = true;
  try {
    const cookie = await accountsStore.browserCapture();
    if (!cookie) {
      captureError.value = "未捕获到 Cookie，请确认浏览器中已登录 B 站";
      return;
    }
    const account = await accountsStore.addAccount(cookie);
    showCaptureConfirm.value = false;
    if (account) emit("select", account.id);
  } catch (e) {
    // 捕获期间保持对话框打开，失败文案显示在框内供重试。
    // 必须走 formatIpcError：原先这里是 String(e)，与 `${e}` 展示等价 ——
    // 用户看到的是 Rust 内部措辞（含命令名与超时秒数）。
    // 它此前逃过了 P2-9 的收口，因为那一轮的判据只搜 `${e}` 模板串。
    captureError.value = formatIpcError(e);
  } finally {
    capturing.value = false;
  }
}

function cancelCaptureCookie() {
  showCaptureConfirm.value = false;
  captureError.value = "";
}

/**
 * 方向键/Home/End 移动选中项，并把焦点一并带过去。
 *
 * roving tabindex 的标准做法：焦点与选中必须同步，否则用户按方向键后
 * 视觉上的选中变了、焦点却还停在原来那一行 —— 下一次按方向键会从旧行
 * 继续算，表现成「按键没反应」。
 *
 * 用 nextTick 等 DOM 更新：tabindex 由 :tabindex 绑定在选中项上，
 * 不等到更新完成就 focus() 会聚焦到一个 tabindex=-1 的元素上
 * （浏览器允许程序化聚焦，但随后 Tab 会跳到别处，行为不一致）。
 *
 * **模板里的绑定必须带 `.capture`（实测踩过，用户报「方向键不能移动选中」）**：
 * 焦点落在行内的「启动/停止」按钮上时，`.down.prevent` 绑在**行**上会失效。
 * 实测（真实 exe + CDP 派发按键）：
 *     焦点在行上   → ArrowDown 生效，选中 0→1
 *     焦点在按钮上 → ArrowDown 无效，选中不变（焦点从 BUTTON 变成 DIV）
 * 原因：事件从按钮冒泡到行时，按钮没有阻止默认行为，浏览器已经把**默认
 * 行为**（把焦点移到下一个可聚焦元素）执行掉了；行上的 handler 虽被调用，
 * 但它拿到的 index 是渲染时闭包捕获的旧值，而焦点已不在那一行 —— 表现为
 * 「按键没反应」。
 * 而 **Tab 进入列表时焦点恰好停在按钮上**（Tab 顺序：行 → 行内按钮），
 * 所以「Tab 后按方向键」必然无效 —— 这正是用户报告的现象。
 * 捕获阶段在事件到达按钮**之前**执行，既能 preventDefault 掐掉浏览器的
 * 默认焦点移动，也能保证 handler 拿到正确的 index。
 *
 * 行元素从**本组件自己的容器**里取，不用 document.querySelectorAll：
 * 后者会命中页面上任何 role="option"（将来若有第二个列表组件就会串位），
 * 而且它依赖「DOM 顺序 == accounts 顺序」这一隐含前提。
 */
const listEl = ref<HTMLElement | null>(null);

/** 方向键/Home/End 移动选中项并把焦点带过去。
 *
 *  **返回「是否真的移动了」**，调用方据此决定要不要 `preventDefault`：
 *  到边界时返回 `false` 且**不**阻止默认行为，好让事件继续冒泡到区域导航
 *  （`src/lib/region-nav.ts`），由它跨到相邻区块 —— 这正是用户确认的
 *  「到区域边缘后再按一次才跨区」：列表内部优先，列表到头的那次按键才交给区域导航。
 *
 *  早前这里是模板上的 `.prevent` 修饰符，它会**无条件** preventDefault，
 *  于是列表到头时事件被吃掉、区域导航永远收不到 —— 跨区功能会静默失效。
 */
function moveSelection(from: number, delta: number): boolean {
  const list = accountsStore.accounts;
  if (list.length === 0) return false;
  const next = Math.min(list.length - 1, Math.max(0, from + delta));
  if (next === from) return false;
  emit("select", list[next].id);
  void nextTick(() => {
    // 行元素从本组件自己的滚动容器里取（见模板上的 ref="listEl"），
    // 不用 document.querySelectorAll —— 后者会命中页面上任何
    // role="option"（将来若有第二个列表组件就会串位）。
    //
    // **必须排除正在离场的节点**：`.account-list-leave-active` 带
    // position:absolute，删除某行后它在 150ms（--duration-fast）过渡期内
    // **仍留在 DOM 里**，而 querySelectorAll 会把它算进索引。
    // 于是 next（accounts 数组索引）与 rows 索引在过渡期内不等价 ——
    // 实测：删除 B 后立刻按下方向键，accounts=[A,C,D] 而 DOM=[A,B,C,D]，
    // rows[1] 指向已删除的 B，焦点被送到 B 上、aria-selected 却在 C 上。
    // 触发窗口就是「删除后 150ms 内按方向键」，键盘用户可稳定复现。
    const rows = listEl.value?.querySelectorAll<HTMLElement>(
      '[role="option"]:not(.account-list-leave-active)',
    );
    rows?.[next]?.focus();
  });
  return true;
}

/** 行上的方向键入口：移动成功才阻止默认行为（见 `moveSelection` 的说明）。 */
function onRowArrow(event: KeyboardEvent, from: number, delta: number): void {
  if (moveSelection(from, delta)) event.preventDefault();
}

/** 拖拽排序。用户要求：整行可拖、半透明跟随、插入位置高亮线、边缘自动滚动、
 *  拖拽期禁文字选中、**不需要键盘替代操作**、纯手动顺序。
 *
 *  **用 SortableJS（经 @vueuse/integrations 的 useSortable），不自己写拖拽**：
 *  指针跟随、占位元素、边缘自动滚动、触屏兼容这一整套自己写要几百行且坑多。
 *  （`@vueuse/integrations` 的 useSortable 内部排序工具直接取自
 *   `Alfred-Skyblue/vue-draggable-plus`，两者同源，这里选前者是因为它的
 *   `sortablejs` 是显式声明的 optional peer，依赖关系更清楚。）
 *
 *  **`forceFallback: true` 不能省**：SortableJS 默认用 HTML5 drag-and-drop
 *  生成拖拽影像，而本项目已确认 HTML5 DnD 在 WebView2 下不可靠
 *  （见 App.vue 侧栏拖拽把手的注释）。fallback 模式走它自己的指针事件 +
 *  一个克隆元素，可控且能自定义样式。
 *
 *  **ref 必须挂在「直接子元素就是账号行」的那一层**（见模板里的 rowsEl）：
 *  SortableJS 排的是容器的**直接子元素**，而 useSortable 默认的 onUpdate 用
 *  `e.oldIndex/newIndex` 直接索引数组（见其 moveArrayElement 实现）。
 *  挂到外层滚动容器上会因为中间隔了一层 TransitionGroup 而一个都排不到。
 */
const rowsEl = ref<HTMLElement | null>(null);
/** 拖拽开始前的 id 顺序。**回滚必须用它**：拖拽结束时数组已经被 SortableJS
 *  改过了，那时再读「当前顺序」拿到的已经是新顺序，拿它当回滚点等于不回滚。 */
let orderBeforeDrag: string[] = [];

// 传 ref 而不是 store 上的裸数组：对 ref 走「复制→改副本→整体赋值」，
// 对裸数组走「原地 splice 再下一拍补回」—— 后者会有一拍「元素凭空少了一个」的中间态。
const { accounts: accountsRef } = storeToRefs(accountsStore);

useSortable(rowsEl, accountsRef, {
  // 容器出现/消失时自动重建：账号列表在 loading / 错误 / 空列表分支下不渲染
  watchElement: true,
  /** 自定义 onUpdate：**只同步数组，绝不搬 DOM**。
   *
   *  不用 useSortable 默认的 `moveArrayElement`，它做两件事：
   *    ① `removeNode(item)` + `insertNodeAt(from, item, oldIndex)`
   *       —— 把 SortableJS 已经摆好的节点**搬回旧位置**；
   *    ② `nextTick` 里改数组，让 Vue 按新顺序再排一遍。
   *  这一来一回让 DOM 先回退再前进，而 TransitionGroup 的 move 过渡是按
   *  「patch 前后的位置差」触发的 —— 位置差被人为造了出来，于是松手后又滑一遍
   *  220ms。这就是用户报的「两套让位动画」的第二个那套（实测：拖拽期间只有
   *  SortableJS 的 150ms 让位；`.no-move-anim` 一摘，全部行同时开始 220ms 过渡，
   *  两轮复现完全一致）。
   *
   *  这里只改数组：SortableJS 触发 onUpdate 之前 DOM 已经在新位置，数组同步成
   *  同一个顺序后，Vue 的 before/after 快照一致 → 位置差为零 → 不产生 move 过渡，
   *  也就不需要再靠加/摘类压制它（`.no-move-anim` 那套补丁治的是症状）。
   *  索引直接用 SortableJS 给的 oldIndex/newIndex：那是容器**直接子元素**的下标，
   *  而本容器（TransitionGroup 的 tag="div"）的直接子元素正好就是账号行。 */
  onUpdate: (e) => {
    // SortableEvent 上这两个字段类型是 `number | undefined`（它们定义在基类
    // 事件上、只有拖拽类事件才有），所以必须显式守卫，不能直接拿去 splice。
    const from = e.oldIndex;
    const to = e.newIndex;
    if (from === undefined || to === undefined) return;
    const next = [...accountsRef.value];
    const [moved] = next.splice(from, 1);
    if (!moved) return;
    next.splice(to, 0, moved);
    accountsRef.value = next;
  },
  // **这个 animation 是拖拽时唯一该有的动画**：SortableJS 靠它让兄弟行
  // 平滑让位（读 dragRect 算目标位置，用 transform 过渡过去）。
  // 2026-10-13 曾把它设成 0，理由是「拖拽会有两次滚动」—— 那是误诊：
  // 关掉它只是把动画全杀了，第二套动画另有来源（见上面 onUpdate）。
  animation: 150,
  forceFallback: true,
  // 克隆体挂到 body：**它现在被 style.css 隐藏了**（`visibility: hidden`），
  // 所以位置本身不影响观感。仍然挂 body 是为了**避开 Vue**：
  // 挂进列表容器（`fallbackOnBody: false`）的话，克隆体会成为 TransitionGroup
  // 那层 div 的子节点，而那个 div 的子元素由 Vue 按 key 管理 ——
  // 下次重渲染会把不认识的那个节点删掉。
  fallbackOnBody: true,
  fallbackClass: "account-row-fallback",
  // 原位置的占位元素 —— 「插入位置高亮线」画在它身上（见 style.css）
  ghostClass: "account-row-ghost",
  // 行内按钮不触发拖拽：否则点「启动/停止」会变成把它拖起来
  filter: "button",
  // **`preventOnFilter` 必须显式关掉**（SortableJS 默认 true）。
  // 默认值会对被 filter 命中的元素调用 `evt.preventDefault()`，而那个 evt 是
  // `mousedown` —— 阻止它的默认行为会**阻止按钮获得焦点**。后果是：
  // 点 B 行的「启动」→ 选中切到 B（handleStart 里 emit select），
  // 但焦点还停在 A 行 → 此后按 ↑/↓ 是从 A 行开始算，与看到的高亮不一致。
  preventOnFilter: false,
  // 边缘自动滚动（SortableJS 默认就开，显式写出来表明是有意为之）
  scroll: true,
  scrollSensitivity: 40,
  scrollSpeed: 12,
  onStart: () => {
    orderBeforeDrag = accountsStore.accounts.map((a) => a.id);
    // 拖拽期禁文字选中：SortableJS 只管被拖的那个元素，指针扫过其它行的
    // 文字时浏览器仍会选中，所以在 body 上整体禁掉。
    document.body.style.userSelect = "none";
    // 兜底：拖拽中窗口失焦（Alt+Tab / 弹出系统窗口）时 mouseup 可能收不到，
    // 那样这个 `userSelect: none` 会永久留在 body 上 —— **整个应用再也选不中文字**，
    // 而且用户完全想不到是「上次拖拽」造成的。所以失焦时也清一次。
    window.addEventListener("blur", clearDragUserSelect, { once: true });
  },
  onEnd: () => {
    clearDragUserSelect();
    void persistOrderAfterDrag();
  },
});

/** 清掉拖拽期的全局禁选态。`onEnd` 与「窗口失焦」两条路都会走它。 */
function clearDragUserSelect() {
  document.body.style.userSelect = "";
  window.removeEventListener("blur", clearDragUserSelect);
}

/** 拖拽结束后把新顺序落盘。
 *
 *  自定义 onUpdate 是**同步**改数组的，而 SortableJS 先派发 `update` 再派发
 *  `end`（见其 `_onDrop`：两个 `_dispatchEvent` 相邻），所以进到这里时
 *  `accountsStore.accounts` 已经是新顺序，不需要再 `await nextTick()` 等它。
 *
 *  失败时 `reorderAccounts` 回滚到 `orderBeforeDrag`。 */
async function persistOrderAfterDrag() {
  const before = orderBeforeDrag;
  const after = accountsStore.accounts.map((a) => a.id);
  // 拖回原位：SortableJS 也会触发 onEnd，但顺序没变，不必落盘
  if (after.length === before.length && after.every((id, i) => id === before[i])) return;
  // 保险：万一 DOM 与数组不同步（例如拖拽中途账号被删），宁可不落盘也不要写坏
  if (after.length !== before.length || new Set(after).size !== after.length) return;
  try {
    await accountsStore.reorderAccounts(after, before);
  } catch (e) {
    showActionError(formatIpcError(e, "保存账号顺序失败"), true);
  }
}

onUnmounted(() => {
  // 拖拽中途卸载时恢复 body 的禁选态，否则整个应用再也选不中文字
  document.body.style.userSelect = "";
});

// 底部「备注/删除」作用于当前选中账号（对齐旧版：行内只保留启动/停止）
function handleBottomRename() {
  if (!props.selectedId) return;
  const acc = accountsStore.accounts.find((a) => a.id === props.selectedId);
  openRenameDialog(props.selectedId, acc?.remark ?? "");
}

function handleBottomRemove() {
  if (!props.selectedId) return;
  handleRemoveAccount(props.selectedId);
}
</script>

<template>
  <!-- 卡片内边距 14/12/14/14、间距 10px，对齐 Qt 时代的账号面板；
       h-full 拉满左栏：列表区弹性伸缩，操作按钮固定在卡底。
       rounded-none：账号栏紧贴窗口左右边缘，圆角会在窗口边界与卡片
       之间露出一小块背景色，看起来像「卡片没贴满」。
       card-hover 的 hover 边框变化保留，它不影响圆角。
       图标条模式已删除，这里不再有 collapsed 分支。 -->
    <Card
      data-nav-region="accounts"
      data-nav-order="2"
      class="card-hover flex h-full flex-col rounded-none"
    >
      <CardHeader class="px-3.5 pb-2.5 pt-3">
      <div class="flex items-center justify-between">
        <!-- 15px 而不是 11pt：11pt = 14.67px，与正文 text-sm（14px）只差
             0.67px，三张卡的标题几乎与正文同大，层级完全靠字重承担 ——
             任何字体回退或 DPI 缩放都可能让标题看起来比正文还小。
             统一到 px 并与另两张卡（TaskProgress / LogViewer）保持
             「15px + font-semibold」同一形态。 -->
        <CardTitle class="text-[15px] font-semibold">账号</CardTitle>
        <span class="text-xs text-muted-foreground">
          {{ accountsStore.accounts.length }} 个
        </span>
      </div>

        <Dialog v-model:open="showAddDialog">
          <DialogContent class="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>添加账号</DialogTitle>
              <DialogDescription>
                粘贴 B 站 Cookie 以添加新账号
              </DialogDescription>
            </DialogHeader>
            <div class="space-y-4 py-4">
              <p
                v-if="addError"
                class="break-all text-xs text-signal-danger"
                role="alert"
              >
                {{ addError }}
              </p>
              <div class="space-y-2">
                <Label for="new-cookie" class="text-sm font-medium">Cookie</Label>
                <Input
                  id="new-cookie"
                  v-model="newCookie"
                  type="password"
                  placeholder="粘贴 B 站 Cookie..."
                  class="font-mono text-xs"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  class="mt-2 h-7 w-full text-xs"
                  :disabled="capturing"
                  @click="handleCaptureCookie"
                >
                  {{ capturing ? "捕获中，请在浏览器完成登录..." : "从浏览器捕获" }}
                </Button>
              </div>
              <div class="flex justify-end gap-2">
                <Button variant="outline" size="sm" @click="showAddDialog = false">
                  取消
                </Button>
                <Button
                  size="sm"
                  :disabled="adding || !newCookie.trim()"
                  @click="handleAddAccount"
                >
                  {{ adding ? "添加中..." : "添加" }}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog v-model:open="showRenameDialog">
          <DialogContent class="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>重命名账号</DialogTitle>
              <DialogDescription>
                修改该账号的备注名称，便于区分多个账号
              </DialogDescription>
            </DialogHeader>
            <div class="space-y-4 py-4">
              <p
                v-if="renameError"
                class="break-all text-xs text-signal-danger"
                role="alert"
              >
                {{ renameError }}
              </p>
              <div class="space-y-2">
                <Label for="rename-value" class="text-sm font-medium">备注名称</Label>
                <Input
                  id="rename-value"
                  v-model="renameValue"
                  placeholder="输入新的备注名称..."
                  maxlength="32"
                  :disabled="renaming"
                  @keydown.enter="handleRenameAccount"
                />
              </div>
              <div class="flex justify-end gap-2">
                <Button variant="outline" size="sm" @click="showRenameDialog = false">
                  取消
                </Button>
                <Button size="sm" :disabled="renaming || !renameValue.trim()" @click="handleRenameAccount">
                  {{ renaming ? "保存中..." : "保存" }}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
    </CardHeader>
    <CardContent class="min-h-0 flex-1 px-3.5 pt-0">
      <!-- 列表容器沿用 Qt 时代 QListWidget 的观感：
           输入框底色 + 1px 边框 + radius 8px + 内 padding 4px。
           用原生 overflow-y-auto 而非引入 reka 的滚动条组件：后者会渲染
           一条独立的隐藏式滚动条元素，CSS 的 ::-webkit-scrollbar 盖不住它，
           而全局隐藏滚动条是本项目的统一要求。 -->
      <div
        ref="listEl"
        class="scroll-hidden h-full overflow-y-auto rounded-lg border border-input bg-input/40 p-1"
      >
        <!-- 骨架行而不是一行「加载中...」文字：
             窗口在 App.vue 的 restoreWindowGeometry 完成（2~4 次轻量 IPC）
             后就显示，而账号列表要等一次完整的 sidecar 往返 —— 这段时间里
             左侧只有一句灰字，用户看到的是「一块什么都没有的区域」。
             骨架行按真实条目的结构（圆点 + 名字 + 按钮）占位，
             尺寸与真行一致，数据到位时不会发生布局跳动。
             aria-hidden：这是纯视觉占位，读屏用户由下方 role="status"
             的文案获知状态（否则会念出 4 个空条目）。 -->
        <div v-if="accountsStore.loading" class="space-y-0.5" role="status">
          <span class="sr-only">正在加载账号列表…</span>
          <div
            v-for="i in 4"
            :key="i"
            aria-hidden="true"
            class="flex items-center justify-between rounded-md border border-border px-2.5 py-2"
          >
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 shrink-0 rounded-full bg-muted" />
              <!-- 宽度写死成几个固定值而不是随机数：随机值每次重渲染都变，
                   骨架自己就在抖，比没有骨架更显廉价 -->
              <span
                class="skeleton h-3.5 rounded"
                :style="{ width: `${[72, 96, 60, 84][i - 1]}px` }"
              />
            </div>
            <span class="skeleton h-7 w-16 shrink-0 rounded-md" />
          </div>
        </div>
        <!-- 错误态：缺了它，sidecar 起不来时 accounts 保持 []，
             下面会渲染「暂无账号」，把故障伪装成空列表 -->
        <div
          v-else-if="accountsStore.error"
          class="space-y-2 py-8 text-center"
          role="alert"
        >
          <p class="break-all text-sm text-signal-danger">
            {{ accountsStore.error }}
          </p>
          <Button size="sm" variant="outline" @click="accountsStore.fetchAccounts()">
            重试
          </Button>
        </div>
        <div
          v-else-if="accountsStore.accounts.length === 0"
          class="py-8 text-center text-sm text-muted-foreground"
        >
          暂无账号，点击下方按钮添加
        </div>
        <!-- relative 是 .account-list-leave-active 里 position: absolute 的定位祖先：
             离开项要脱离文档流（否则它在 leave 期间仍占位，后面的行要等它消失
             才动，-move 过渡的起点就是错的），而 absolute 需要最近的定位祖先
             来界定 left/right 的参照。

             **ref="rowsEl" 是拖拽排序的容器**：SortableJS 排的是容器的**直接子元素**，
             而这里 tag="div" 渲染出的那层 div 的直接子元素正好就是账号行。
             （ref 挂在 TransitionGroup 组件上也能拿到 DOM：VueUse 的 unrefElement
               实现是 `plain?.$el ?? plain`，会自己取组件实例的 $el。）
             `watchElement: true` 让它在「空列表 / 加载中」分支下不渲染时能自动补建。 -->
        <TransitionGroup
          v-else
          ref="rowsEl"
          name="account-list"
          tag="div"
          class="relative space-y-0.5"
          role="listbox"
          aria-label="账号列表"
        >
          <!-- roving tabindex：只有当前选中项可 Tab 聚焦（tabindex=0），
               其余为 -1 —— 这是 role="listbox" 的标准交互。
               此前每行都是 tabindex="0"，于是键盘用户要按 N+1 次 Tab
               才能穿过账号列表（N = 账号数）。
               方向键/Home/End 由 moveSelection 处理，焦点与选中同步移动。

               **`@focus` 也要 emit select（焦点即选中）**：单选框语义的
               listbox 里焦点与选中必须同步，否则会出现「焦点环在这一行、
               高亮却在另一行」。这条不是理论顾虑 —— 区域导航
               （src/lib/region-nav.ts）的 ↑/↓ 会把焦点送到区域内任意停靠点，
               包括**未被选中**的账号行（例如从底部「添加账号」往上按）。
               加上它之后任何来源的焦点（点击 / Tab / 区域导航 / moveSelection）
               都会把选中带过去，两边不会再分叉。
               `@focus` 与 `@click` 同时触发是幂等的（同一个 id 重复 emit 无副作用）。 -->
          <!-- transition-property 写成含 box-shadow 的显式列表，而不是
               transition-colors：选中态靠 inset 阴影画边框，而 transition-colors
               不含 box-shadow —— 于是同一行里背景色有过渡、边框阴影瞬变，
               选中切换会「先亮背景、再硬跳边框」。 -->
          <div
            v-for="(account, index) in accountsStore.accounts"
            :key="account.id"
            role="option"
            data-nav-self-managed
            :tabindex="account.id === selectedId ? 0 : -1"
            :aria-selected="account.id === selectedId"
            :aria-label="`${account.remark}，${account.running ? '运行中' : '未运行'}`"
            class="mx-px flex cursor-pointer items-center justify-between rounded-md border border-border px-2.5 py-2 transition-[color,background-color,border-color,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="[
              // 运行态只由行内的状态圆点与文字颜色表达，不再叠一层边框动画：
              // 原实现在四边各铺一条独立 background-image 并各自流动，
              // 四个方向互不相同，视觉上就是「扫描线」而不是流动虚线框。
              account.id === selectedId
                ? 'bg-accent shadow-[inset_0_0_0_1px_var(--color-primary)]'
                : 'hover:bg-accent/50',
            ]"
            @click="emit('select', account.id)"
            @focus="emit('select', account.id)"
            @keydown.enter.prevent="emit('select', account.id)"
            @keydown.space.prevent="emit('select', account.id)"
            @keydown.down.capture="onRowArrow($event, index, 1)"
            @keydown.up.capture="onRowArrow($event, index, -1)"
            @keydown.home.capture="onRowArrow($event, index, -index)"
            @keydown.end.capture="onRowArrow($event, index, accountsStore.accounts.length - 1 - index)"
          >
            <div class="flex min-w-0 items-center gap-2">
              <!-- 运行状态由行级 aria-label 提供，圆点本身对读屏隐藏 -->
              <span
                aria-hidden="true"
                class="h-2 w-2 shrink-0 rounded-full transition-colors"
                :class="account.running ? 'bg-signal-success' : 'bg-muted'"
              />
              <p
                class="truncate text-sm leading-tight font-medium transition-colors"
                :class="account.running ? 'text-signal-success' : 'text-foreground'"
              >
                {{ account.remark }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <!-- 启停合为一个按钮，variant 动态绑定。
                   早前用 v-if / v-else 写两个 Button：点「停止」时
                   account.running 翻 false，旧按钮被销毁、新按钮被创建，
                   而 transition-colors 只在同一 DOM 节点上生效 —— 节点替换
                   不产生过渡，加上 variant 从 destructive（红底白字）跳到
                   outline（白底描边）整套配色突变，视觉上就是「闪一下」。
                   单按钮后 variant 只是 class 变化，过渡正常生效。 -->
              <Button
                size="sm"
                :variant="account.running ? 'destructive' : 'outline'"
                class="h-7 w-16 rounded-md px-0 text-xs"
                :disabled="isPending(account.id)"
                @click.stop="account.running ? handleStop(account.id) : handleStart(account.id)"
              >
                {{ account.running ? "停止" : "启动" }}
              </Button>
            </div>
          </div>
        </TransitionGroup>
      </div>
    </CardContent>

    <!-- 底部操作区：添加账号全宽 + 备注/删除对半 -->
    <div class="flex flex-col gap-2.5 px-3.5 pb-3.5 pt-2.5">
      <p
        v-if="actionError"
        class="break-all text-xs text-signal-danger"
        role="alert"
        aria-live="polite"
      >
        {{ actionError }}
      </p>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button class="w-full rounded-md">添加账号</Button>
        </DropdownMenuTrigger>
        <!-- 必须 side="top"：菜单挂在按钮正下方会被窗口底部截断，
             而这个按钮就在左栏最下缘。 -->
        <DropdownMenuContent align="center" side="top" class="w-40">
          <DropdownMenuItem @select="emit('qr-login')">扫码登录</DropdownMenuItem>
          <DropdownMenuItem @select="showAddDialog = true">手动粘贴 Cookie</DropdownMenuItem>
          <DropdownMenuItem @select="handleCaptureCookie">浏览器自动捕获</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <div class="grid grid-cols-2 gap-1.5">
        <Button
          variant="outline"
          class="rounded-md"
          :disabled="!selectedId"
          @click="handleBottomRename"
        >
          备注
        </Button>
        <!-- 「删除」保留全局禁用（pendingActions 非空即禁用），
             与行内启停的按行禁用不同：删除会连带 stop_miner + 清缓存 + 删库，
             在任何一个账号启停在途时做这件事，失败原因极难归到正确的操作上。 -->
        <Button
          variant="outline"
          class="rounded-md text-destructive hover:bg-destructive/10"
          :disabled="!selectedId || pendingActions.size > 0"
          @click="handleBottomRemove"
        >
          删除
        </Button>
      </div>
    </div>
  </Card>

  <Dialog v-model:open="showCaptureConfirm">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>从浏览器捕获 Cookie</DialogTitle>
        <DialogDescription v-if="!capturing">
          即将打开浏览器捕获 B 站 Cookie，请确保已登录 B 站。捕获过程可能需要 1-2 分钟。
        </DialogDescription>
        <DialogDescription v-else>
          正在打开浏览器捕获 Cookie，请在浏览器完成 B 站登录并耐心等待（最长 120 秒）...
        </DialogDescription>
      </DialogHeader>
      <p v-if="captureError" class="text-sm text-signal-danger" role="alert">
        捕获失败: {{ captureError }}
      </p>
      <div class="flex justify-end gap-2">
        <Button variant="outline" size="sm" @click="cancelCaptureCookie">
          {{ capturing ? "关闭（后台继续）" : "取消" }}
        </Button>
        <Button size="sm" :disabled="capturing" @click="confirmCaptureCookie">
          {{ capturing ? "捕获中..." : captureError ? "重试" : "确认捕获" }}
        </Button>
      </div>
    </DialogContent>
  </Dialog>

  <!-- 删除账号确认（替代原生 confirm，避免阻塞 WebView） -->
  <ConfirmDialog
    :open="showRemoveConfirm"
    title="删除账号"
    :message="`确定要删除账号「${removeTargetRemark}」吗？该操作不可撤销。`"
    :error="removeError"
    confirm-text="删除"
    loading-text="删除中…"
    variant="destructive"
    :loading="removing"
    @update:open="showRemoveConfirm = $event"
    @confirm="confirmRemoveAccount"
    @cancel="cancelRemoveAccount"
  />
</template>

