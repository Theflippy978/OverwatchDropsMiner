<script setup lang="ts">
/**
 * 输入框专用的自绘右键菜单。
 *
 * 为什么不用浏览器原生菜单：原生菜单里混着「后退 / 前进 / 刷新 /
 * 另存为 / 查看源代码 / 检查」这类在桌面应用里毫无意义、且会暴露调试入口
 * 的项。Tauri 2 的 wry 没有裁剪原生菜单项的公开 API，只能整体关闭后
 * 自绘。整体关闭又会让「在输入框里右键粘贴」这条路径消失，所以在这里
 * 把常用的编辑操作补回来。
 *
 * 刻意不含「剪切」：本项目所有可编辑处都是单行文本框或数字框，
 * 剪切后清空输入框没有实际价值，反而多一个误触点。
 *
 * 为什么是纯 div 而不用项目的 DropdownMenu：Radix/reka 的 MenuContent
 * 靠 Popper 定位，而 Popper 需要一个 Trigger 提供锚点矩形 —— 本组件
 * 没有触发器，锚点退化成 (0,0)，再叠上内联的 left/top 就是两套定位
 * 互相打架，菜单位置不可靠。纯 fixed 浮层只有一套坐标系。
 *
 * 右键策略由本组件**独占**：非输入框区域也在同一个捕获阶段监听里
 * preventDefault。此前 App.vue 与本组件各注册一个 document 捕获监听器、
 * 且都对输入框放行，导致在输入框上右键时谁都不 preventDefault，
 * 原生菜单照常弹出（用户实锤），自绘菜单形同虚设。
 *
 * 粘贴的三级回退见 insertFromClipboard 的注释 —— 这是本组件唯一
 * 不能靠静态检查保证正确的地方。
 */
import { computed, nextTick, ref } from "vue";
import { useEventListener, useTimeoutFn } from "@vueuse/core";
import { ClipboardPaste, ClipboardCopy, ClipboardType, RotateCcw, MousePointerClick } from "lucide-vue-next";

type MenuKey = "undo" | "copy" | "paste" | "pasteText" | "selectAll";

const open = ref(false);
/** 菜单左上角坐标（视口坐标）。用 clientX/clientY + position:fixed，
    不像 Popper 那样需要锚点元素，因此不受「有没有 Trigger」影响。 */
const position = ref({ x: 0, y: 0 });
/** 右键按下的那个元素。菜单项据此决定能否执行（无选中就不给复制）。 */
const target = ref<HTMLInputElement | HTMLTextAreaElement | null>(null);
const menuRef = ref<HTMLElement | null>(null);

const isMac = /Mac|iPhone|iPad/.test(navigator.platform ?? "");

const canUndo = ref(false);
const canCopy = ref(false);
/** 粘贴恒可用：能否真正读到剪贴板要等用户点了才知道（`readText()` 可能因
    权限或非安全上下文失败），在这里预先探测反而要多一次权限请求。
    故不用 ref —— 它从不被写，用 ref 只会让人以为有「按状态禁用」的逻辑。 */
const canPaste = true;
const canSelectAll = ref(false);

/** 选区是否为空。空选区时禁用复制/全选，避免菜单项点了没反应。 */
function refreshSelectionState() {
  const el = target.value;
  if (!el) {
    canUndo.value = canCopy.value = canSelectAll.value = false;
    return;
  }
  const { selectionStart, selectionEnd, value } = el;
  const hasSelection =
    typeof selectionStart === "number" && selectionStart !== selectionEnd;
  canUndo.value = true;
  canCopy.value = hasSelection && !!value;
  canSelectAll.value = !!value;
}

/** 把文本写回输入框并触发框架能感知的事件。
    只改 value 不派发 input 事件的话，Vue 的 v-model 不会更新，
    用户粘贴后界面显示与实际数据不一致，提交时才暴露。 */
function writeToTarget(text: string) {
  const el = target.value;
  if (!el) return;
  el.focus();
  if (typeof el.setRangeText === "function") {
    el.setRangeText(text, el.selectionStart ?? 0, el.selectionEnd ?? 0, "end");
  } else {
    const start = el.selectionStart ?? 0;
    const end = el.selectionEnd ?? 0;
    el.value = el.value.slice(0, start) + text + el.value.slice(end);
    el.setSelectionRange(start + text.length, start + text.length);
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

/**
 * 读取系统剪贴板并插入。
 *
 * 三级回退，因为每一级都可能失败且失败原因不同：
 * 1. `navigator.clipboard.readText()` —— 标准路径，但需要
 *    clipboard-read 权限，且在非安全上下文里直接抛 SecurityError。
 * 2. `document.execCommand('paste')` —— Chromium 已禁用，WebView2 上
 *    是否可用随版本变化，不报错但可能静默无效。
 * 3. 都不行时提示用户用 Ctrl+V，而不是让菜单项点了没反应。
 */
const clipboardHint = ref("");
/** 剪贴板提示 4 秒后自动消失。start() 的语义是「先清掉上一次的计时再重新计时」，
 *  与原先的 clearTimeout + setTimeout 等价；清理由作用域托管。 */
const { start: scheduleHintHide } = useTimeoutFn(
  () => {
    clipboardHint.value = "";
  },
  4000,
  { immediate: false },
);

async function insertFromClipboard(asPlainText: boolean) {
  const el = target.value;
  if (!el) return;
  el.focus();
  try {
    const text = await navigator.clipboard.readText();
    // 「粘贴为纯文本」在此与普通粘贴等价：输入框本身不解析富文本，
    // 剪贴板里的 HTML 分支不会被写入。保留独立菜单项是为了让
    // 从网页复制内容时用户有明确的预期。
    writeToTarget(asPlainText ? text.replace(/\r\n?/g, "\n") : text);
    return;
  } catch {
    // 落到下一级
  }
  try {
    if (document.execCommand("paste")) return;
  } catch {
    // 落到提示
  }
  clipboardHint.value = "浏览器未授权读取剪贴板，请用 Ctrl+V";
  scheduleHintHide();
}

/** execCommand 的目标必须是当前焦点所在元素，否则作用在 body 上：
    表现为菜单项闪一下但输入框内容没变。 */
function execCommand(command: "undo" | "copy" | "selectAll") {
  target.value?.focus();
  document.execCommand(command);
  refreshSelectionState();
}

interface MenuItem {
  key: MenuKey;
  label: string;
  shortcut: string;
  enabled: boolean;
  icon: typeof RotateCcw;
}

const mod = isMac ? "⌘" : "Ctrl";

const items = computed<MenuItem[]>(() => [
  { key: "undo", label: "撤销", shortcut: `${mod}Z`, enabled: canUndo.value, icon: RotateCcw },
  { key: "copy", label: "复制", shortcut: `${mod}C`, enabled: canCopy.value, icon: ClipboardCopy },
  { key: "paste", label: "粘贴", shortcut: `${mod}V`, enabled: canPaste, icon: ClipboardPaste },
  // 图标必须是「粘贴」语义。原先是 Scissors（剪刀）—— 那是「剪切」的通用
  // 图形，与本文件开头「刻意不含剪切」的声明直接冲突，用户会以为这一项是剪切。
  // 用 ClipboardType：与「粘贴」的 ClipboardPaste 同族，且「纯文本」的语义
  // 由 T 字形承载，不会与普通粘贴混淆。
  { key: "pasteText", label: "粘贴为纯文本", shortcut: "", enabled: canPaste, icon: ClipboardType },
  { key: "selectAll", label: "全选", shortcut: `${mod}A`, enabled: canSelectAll.value, icon: MousePointerClick },
]);

function close() {
  open.value = false;
  target.value = null;
}

async function run(key: MenuKey) {
  if (key === "paste") await insertFromClipboard(false);
  else if (key === "pasteText") await insertFromClipboard(true);
  else execCommand(key);
  // 粘贴提示需要在菜单仍开着时才看得见，其余操作立即关闭。
  if (!clipboardHint.value) close();
}

/** 菜单贴边收敛：贴近右/下边缘时向内翻，避免浮层被窗口裁掉。 */
async function openAt(x: number, y: number) {
  position.value = { x, y };
  open.value = true;
  await nextTick();
  const el = menuRef.value;
  if (!el) return;
  const { width, height } = el.getBoundingClientRect();
  const margin = 8;
  let left = x;
  let top = y;
  if (left + width > window.innerWidth - margin) left = Math.max(margin, x - width);
  if (top + height > window.innerHeight - margin) top = Math.max(margin, y - height);
  position.value = { x: left, y: top };
}

function isEditable(el: Element | null): el is HTMLInputElement | HTMLTextAreaElement {
  return el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
}

function onDocumentContextMenu(event: MouseEvent) {
  // 无论命中什么，一律掐掉 WebView2 的原生菜单：它在本应用里只有坏处
  // （暴露「检查」等调试入口 + 在输入框里抢走粘贴路径）。
  event.preventDefault();
  event.stopPropagation();

  const hit = event.target as Element | null;
  const el = hit?.closest("input, textarea, [contenteditable='true']");
  // contenteditable 不是 input/textarea，写入路径要另走 execCommand，
  // 故不在此提供自绘菜单，只吞掉原生菜单。
  if (!el || !isEditable(el)) {
    close();
    return;
  }
  // 数字输入框的原生微调按钮/选区行为与自绘菜单冲突不大，
  // 但禁用态输入框（如「保存中…」的备注框）右键没意义。
  if (el.disabled || el.readOnly) {
    close();
    return;
  }
  target.value = el;
  refreshSelectionState();
  void openAt(event.clientX, event.clientY);
}

function onPointerDown(event: PointerEvent) {
  if (!open.value) return;
  if (menuRef.value?.contains(event.target as Node)) return;
  close();
}

function onKeyDown(event: KeyboardEvent) {
  if (event.key === "Escape") close();
}

/** 滚动时菜单不再贴着光标，留在原地会造成「菜单属于某个旧位置」的错觉。 */
function onScrollOrResize() {
  if (open.value) close();
}

// 捕获阶段：抢在组件自身可能存在的 contextmenu handler 之前。
// 注册在 setup 同步阶段（比 onMounted 更早），对本组件更安全 ——
// 监听先于任何渲染与交互存在。摘除由 useEventListener 随作用域托管，
// 因此不再需要成对地手写 add/remove。
useEventListener(document, "contextmenu", onDocumentContextMenu, { capture: true });
useEventListener(document, "pointerdown", onPointerDown, { capture: true });
useEventListener(document, "keydown", onKeyDown, { capture: true });
useEventListener(window, "scroll", onScrollOrResize, { capture: true });
useEventListener(window, "resize", onScrollOrResize);
useEventListener(window, "blur", onScrollOrResize);
</script>

<template>
  <Teleport to="body">
    <!--
      role="menu" + role="menuitem"：自绘浮层不继承任何语义，
      读屏用户否则完全感知不到它的存在。
      不用 v-if 之外的条件渲染（无 transition）：菜单是瞬时响应用户右键的
      控件，加进出场动画反而让它「看起来像从别处飘来」。
    -->
    <div
      v-if="open"
      ref="menuRef"
      role="menu"
      aria-label="编辑操作"
      class="fixed z-[100] min-w-44 select-none overflow-hidden rounded-md
             border border-border bg-popover p-1 text-popover-foreground shadow-md"
      :style="{ left: `${position.x}px`, top: `${position.y}px` }"
    >
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        role="menuitem"
        :disabled="!item.enabled"
        class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm
               transition-colors hover:bg-accent hover:text-accent-foreground
               focus-visible:bg-accent focus-visible:outline-none
               disabled:pointer-events-none disabled:opacity-50"
        @click="run(item.key)"
      >
        <component :is="item.icon" class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span class="flex-1">{{ item.label }}</span>
        <span
          v-if="item.shortcut"
          class="shrink-0 text-[11px] tracking-widest text-muted-foreground"
        >
          {{ item.shortcut }}
        </span>
      </button>
      <p
        v-if="clipboardHint"
        class="notice-appear border-t border-border px-2 py-1.5 text-[11px] text-signal-warning"
        role="status"
      >
        {{ clipboardHint }}
      </p>
    </div>
  </Teleport>
</template>