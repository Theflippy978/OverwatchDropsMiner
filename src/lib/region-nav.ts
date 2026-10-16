/** 方向键区域导航：把 ↑/↓ 从「只有账号列表能用」扩展到全界面。
 *
 *  用户报告：「为什么只有账号列表能被方向键控制 而其他的按钮不能控制」。
 *  本模块实现用户逐项确认的设计（2026-10-10）：
 *
 *  1. **到区域边缘后再按一次才跨区**：区域内方向键优先，已经在区域最上/最下
 *     还继续按就跳到相邻区域；到链首/链尾**停住**（不环绕）。
 *  2. **输入框内保持原生**：`number` 的 ↑/↓ 仍用于增减数值、文本框的 ←/→ 仍移光标，
 *     一律不抢（判据见 `nav-geometry.ts` 的 `isTextEntry`）。
 *  3. **记住该区域上次离开时聚焦的元素**，首次进入按来向落到最近的一头。
 *  4. **参与区块 4 个**：标题栏 / 左栏账号列表 / 配置卡 / 挂宝进度卡。
 *     日志卡、侧栏拖拽把手、右栏滚动容器**不参与**（它们没有 `data-nav-region`）。
 *
 *  区域链的顺序由 `data-nav-order` 显式给出，**不靠 DOM 顺序** ——
 *  链序是用户拍板的决定，写进标记才看得见，也才能在门禁里断言。
 *
 *  横向（←/→）只在**当前行内**移动，到行首/行末停住、**不跨区**：
 *  横向没有「相邻区域」的概念，硬跨只会跳到别的栏，违反直觉。
 *
 *  本文件只做 DOM 胶水；所有判定逻辑在 `nav-geometry.ts`（零 import，
 *  所以外部 Node 脚本能直接 import 真代码来测，不必复刻一遍）。
 */
import {
  groupIntoRows,
  horizontalTarget,
  isTextEntry,
  orderRegionIds,
  verticalTarget,
  type StopBox,
} from "@/lib/nav-geometry";

/** 标在区域容器上；值必须全局唯一（它同时是链序比较与「上次焦点」记忆的键）。 */
export const REGION_ATTR = "data-nav-region";
/** 区域在链里的序号（整数，升序）。 */
export const ORDER_ATTR = "data-nav-order";
/** 标在「自己处理 ↑/↓」的元素上（账号行就是：它有自己的 roving tabindex + 选中联动）。
 *  区域导航遇到它时**不做区内 ↑/↓ 移动**；事件能冒泡上来即表示它已到边界，直接跨区。 */
export const SELF_MANAGED_ATTR = "data-nav-self-managed";

/** 可聚焦元素的选取范围。
 *
 *  含 `[role="option"]` 是刻意的：账号行只有**选中那行**是 `tabindex=0`，
 *  其余是 `-1`（roving tabindex 的标准做法）。不把它们算进停靠点的话，
 *  「行 → 行内按钮」的 ←/→ 就找不到目标。
 *  它们出现在停靠点里是安全的：焦点本来就落不到 `tabindex=-1` 的行上，
 *  而 ↑/↓ 在账号列表里由行自己处理（`SELF_MANAGED_ATTR`）。 */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[role="option"]',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/** 正在做离场过渡的元素必须排除。
 *
 *  Vue 的 `TransitionGroup` 在 leave 期**仍把元素留在 DOM 里**（本项目 150ms），
 *  而且它带着离场前的 `tabindex` —— 若删的是选中行，那就是 `0`。
 *  不排除的话它会变成一个**幽灵停靠点**：↑/↓ 可能把焦点送上去，
 *  150ms 后元素消失、焦点掉回 body。
 *  这与 `AccountList.moveSelection` 里排除 `.account-list-leave-active`
 *  是同一类坑（那边曾导致「删除后立刻按方向键，焦点送到已删除的行上」）。
 *  只能按类名排除：TransitionGroup 给元素加类，加不了自定义属性。 */
const LEAVING_SELECTOR = ".account-list-leave-active";

/** 元素此刻是否真的可聚焦。
 *
 *  优先用 `checkVisibility({ checkVisibilityCSS: true })` —— 它一次覆盖
 *  `display:none` / `visibility:hidden` / `content-visibility`；老引擎没有就退回
 *  `getClientRects()`（只覆盖 `display`）。
 *  本项目的 `invisible`（= `visibility:hidden`）已用在 UpdateDialog 的转圈上，
 *  所以这条不是理论顾虑 —— 那个元素哪天变成可聚焦，退回方案会把它当活停靠点。 */
function visible(el: HTMLElement): boolean {
  if (typeof el.checkVisibility === "function") {
    return el.checkVisibility({ checkVisibilityCSS: true });
  }
  return el.getClientRects().length > 0;
}

function toBox(el: HTMLElement): StopBox {
  const rect = el.getBoundingClientRect();
  return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right };
}

function collectStops(region: HTMLElement): HTMLElement[] {
  return Array.from(region.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => visible(el) && el.closest(LEAVING_SELECTOR) === null,
  );
}

/** 安装区域导航，返回卸载函数。挂在 `App.vue` 的 `onMounted` 上。 */
export function installRegionNav(): () => void {
  /** 每个区域**最近一次**聚焦的元素（不限于「键盘跨区离开时」）。
   *  用 `focusin` 记录而不是只在 `cross()` 里记：鼠标点进某个区块、
   *  或用 Tab 离开时也能更新记忆，否则按方向键跳回来会落在一个早已过时的位置。
   *  用 WeakMap 而不是 Map：区域元素被卸载时自动释放。 */
  const lastFocus = new WeakMap<HTMLElement, HTMLElement>();

  function onFocusIn(event: FocusEvent): void {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const region = target.closest<HTMLElement>(`[${REGION_ATTR}]`);
    if (region) lastFocus.set(region, target);
  }

  /** 当前参与导航的区域，按 `data-nav-order` 升序。每次按键现算 ——
   *  区块会随状态出现/消失（如加载失败态），缓存反而要维护失效逻辑。 */
  function regionChain(): HTMLElement[] {
    const found = Array.from(document.querySelectorAll<HTMLElement>(`[${REGION_ATTR}]`));
    const byId = new Map<string, HTMLElement>();
    const entries: { id: string; order: number | null }[] = [];
    for (const el of found) {
      const id = el.getAttribute(REGION_ATTR) ?? "";
      if (!id || byId.has(id)) continue; // 重复 id 只认第一个，避免链里出现同一个区域两次
      byId.set(id, el);
      const raw = el.getAttribute(ORDER_ATTR);
      const parsed = raw === null ? Number.NaN : Number.parseInt(raw, 10);
      entries.push({ id, order: Number.isFinite(parsed) ? parsed : null });
    }
    return orderRegionIds(entries)
      .map((id) => byId.get(id))
      .filter((el): el is HTMLElement => el !== undefined && visible(el));
  }

  /** 进入区域，返回**是否真的移动了焦点**。
   *
   *  返回值的用途见 `cross`：`focus()` 在一个没有可聚焦元素的区块上
   *  （配置卡处于加载态时就是空的）是个静默的空操作 —— 不区分的话
   *  调用方会把按键吃掉，用户看到的是「按了没反应」。 */
  function focusInto(region: HTMLElement, dir: 1 | -1): boolean {
    const remembered = lastFocus.get(region);
    if (remembered && region.contains(remembered) && visible(remembered)) {
      remembered.focus();
      return true;
    }
    const stops = collectStops(region);
    if (stops.length === 0) return false;
    // 从上往下进来落到第一项，从下往上进来落到最后一项 —— 与移动方向一致
    stops[dir === 1 ? 0 : stops.length - 1].focus();
    return true;
  }

  /** 跨到相邻区域。到链首/链尾、或一路都没有可聚焦元素时返回 false
   *  （调用方据此**不** preventDefault，把按键还给浏览器）。 */
  function cross(region: HTMLElement, dir: 1 | -1): boolean {
    const chain = regionChain();
    const idx = chain.indexOf(region);
    if (idx < 0) return false;
    // 跳过当前没有可聚焦元素的区块：否则焦点不动却返回 true，
    // 调用方会把按键吃掉 —— 表现成「按方向键没反应」，而且再也出不去。
    for (let i = idx + dir; i >= 0 && i < chain.length; i += dir) {
      if (focusInto(chain[i], dir)) return true;
    }
    return false;
  }

  function onKeyDown(event: KeyboardEvent): void {
    // 更内层的处理者已经消费掉这次按键（如账号行的捕获阶段 handler）→ 不抢
    if (event.defaultPrevented) return;
    // 带修饰键的是别的快捷键（Ctrl/Alt/Win 组合），不是导航
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    // 中文输入法**组字期间**方向键是在候选词列表里选字，抢了就打不出中文。
    // 组字必然发生在可编辑元素里，而下面 `isTextEntry` 已经会拦掉 ——
    // 这里是纵深防御：`isComposing` 在组字刚结束时还会短暂为真。
    if (event.isComposing) return;

    const key = event.key;
    const isVertical = key === "ArrowUp" || key === "ArrowDown";
    const isHorizontal = key === "ArrowLeft" || key === "ArrowRight";
    if (!isVertical && !isHorizontal) return;

    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return;
    // 输入框内保持原生：number 的 ↑/↓ 调值、文本框的 ←/→ 移光标，一律不抢
    if (isTextEntry(active.tagName, active.getAttribute("type"), active.isContentEditable)) return;

    const region = active.closest<HTMLElement>(`[${REGION_ATTR}]`);
    // 焦点不在任何参与区块里（弹窗内、日志卡里）→ 不管
    if (!region) return;

    const dir: 1 | -1 = key === "ArrowDown" || key === "ArrowRight" ? 1 : -1;
    const stops = collectStops(region);
    if (stops.length === 0) return;
    const current = stops.indexOf(active);
    if (current < 0) {
      // 焦点落在区域内的非停靠元素上（例如容器本身）→ 收进第一个停靠点
      stops[0].focus();
      event.preventDefault();
      return;
    }

    if (isHorizontal) {
      const boxes = stops.map(toBox);
      const rows = groupIntoRows(boxes);
      const target = horizontalTarget(rows, current, dir);
      // 行内到边界 → 停住，不跨区（用户确认的是「到边界停住」）
      if (target === null) return;
      stops[target].focus();
      event.preventDefault();
      return;
    }

    // ↑/↓：先看该元素是否自己管（账号行就是）
    const selfManaged = active.closest(`[${SELF_MANAGED_ATTR}]`);
    if (selfManaged && region.contains(selfManaged)) {
      // 事件能冒泡到这里 = 它没消费这次按键 = 它已经到边界了 → 直接跨区
      if (cross(region, dir)) event.preventDefault();
      return;
    }

    const boxes = stops.map(toBox);
    const rows = groupIntoRows(boxes);
    const target = verticalTarget(boxes, rows, current, dir);
    if (target === null) {
      // 区域内已到最上/最下一行 → 跨到相邻区域；链首/链尾则停住
      // （此时刻意不 preventDefault：让方向键仍能滚动本区域）
      if (cross(region, dir)) event.preventDefault();
      return;
    }
    stops[target].focus();
    event.preventDefault();
  }

  // **冒泡阶段**（不是捕获）：这样区域自己的 handler（账号行的 `.capture`）先跑，
  // 它消费掉按键后本函数在 `event.defaultPrevented` 处直接返回，两边不打架。
  document.addEventListener("keydown", onKeyDown);
  // focusin 会冒泡（focus 不会），所以能挂在 document 上收全部焦点变化
  document.addEventListener("focusin", onFocusIn);
  return () => {
    document.removeEventListener("keydown", onKeyDown);
    document.removeEventListener("focusin", onFocusIn);
  };
}
