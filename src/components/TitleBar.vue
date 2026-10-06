<script setup lang="ts">
/**
 * 自绘标题栏（配合 tauri.conf.json 的 decorations: false）。
 *
 * 结构：左侧应用图标 + 名称，中间全局状态胶囊，右侧 Windows 风格三键。
 * 中间大片留空是**拖拽区**（data-tauri-drag-region），窗口按钮与胶囊上
 * 显式标注 data-tauri-drag-region="false"，否则在按钮上按下会变成拖窗口。
 */
import { ref, onMounted, onUnmounted, computed } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { getVersion } from "@tauri-apps/api/app";
import {
  Users,
  Minus,
  Square,
  Copy,
  X,
  Sun,
  Moon,
  RefreshCw,
  Check,
  AlertTriangle,
} from "lucide-vue-next";
import appIcon from "../../src-tauri/icons/128x128.png";

const props = defineProps<{
  /** 运行中的账号数，0 表示未运行 */
  runningCount: number;
  /** 当前是否深色主题 */
  dark: boolean;
  /** 手动检查更新的请求态；'idle' 时按钮可用 */
  checkingUpdate: boolean;
  /**
   * 检查结果提示。为空串时中段胶囊显示运行状态。
   * 与运行状态互斥而非叠加：两者都是「用户扫一眼就知道」的信息，
   * 并排显示会让胶囊撑到把标题栏挤变形。
   */
  updateNotice: string;
  /** 提示是否出错（决定胶囊配色） */
  updateNoticeError: boolean;
}>();

const emit = defineEmits<{
  (e: "toggle-theme"): void;
  (e: "check-update"): void;
}>();

const isMaximized = ref(false);
let unlistenResize: (() => void) | null = null;

/** 应用版本号，读 tauri.conf.json 的 version 字段，随打包自动同步。
    拿不到时留空而不是显示占位符：标题栏空间有限，
    「v」比空白更醒目。 */
const version = ref("");

const win = getCurrentWindow();

/**
 * 双击拖拽区切换最大化。
 *
 * data-tauri-drag-region 只提供「按下拖动」，不包含双击语义 —— Tauri 的
 * 拖拽由 wry 在原生层处理，DOM 侧收不到完整的 dblclick 语义（第一次
 * mousedown 就被 wry 接管去拖窗口了）。所以这里额外监听 dblclick。
 * 按钮区标了 data-tauri-drag-region="false"，但其子元素可能没继承属性，
 * 这里再挡一次，避免在窗口按钮上双击误触发最大化。
 */
function onDragRegionDblClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (target?.closest('[data-tauri-drag-region="false"]')) return;
  void toggleMaximize();
}

/** 最大化后按钮显示「还原」图标而非「最大化」，需跟随真实窗口状态 */
async function syncMaximized() {
  try {
    isMaximized.value = await win.isMaximized();
  } catch (e) {
    console.warn("读取最大化状态失败:", e);
  }
}

async function minimize() {
  await win.minimize();
}

/**
 * 标题栏按钮一律走 toggleMaximize 而不是直接 maximize/unmaximize：
 * Windows 上双击标题栏、系统快捷键、Snappy 贴靠布局都会改变最大化状态，
 * 直接调 maximize() 在某些状态下会无效或产生反向跳变。
 */
async function toggleMaximize() {
  await win.toggleMaximize();
  await syncMaximized();
}

async function close() {
  // 不直接调 win.close()：关闭要走 App.vue 的 registerCloseHandler 链路
  // （存配置 → 存几何 → 通知 sidecar 退出），那里已注册 onCloseRequested
  // 并 preventDefault。直接 close() 同样会触发该事件，行为一致。
  await win.close();
}

const statusText = computed(() =>
  props.runningCount > 0
    ? `${props.runningCount} 个账号运行中`
    : "未运行任何账号",
);

/** 胶囊当前显示什么：结果提示优先于运行状态（互斥，见 props.updateNotice 注释）。
    它同时是 <Transition> 的 key —— 每次变化都会让内容整组重新挂载并播放动画。 */
const capsuleText = computed(() => props.updateNotice || statusText.value);

/** 胶囊固定宽度：写在模板的 `w-[132px]` 上（Tailwind 任意值），
    不再用 JS 算 —— 算出来的宽度会随文案变，误差就是抖动本身。

    132px 的来历：canvas measureText 量到的最宽一档是「发现新版本 v1.2.0」
    文字 86px，加图标 12px、间距 6px、两端 padding 20px、边框 2px
    共 126px，留 6px 余量。常见文案都更短（「正在检查…」文字仅 52px），
    右侧会空一块 —— 这个取舍值得：胶囊是状态指示位、不承载精确排版，
    而抖动在常驻标题栏里比空一块显眼得多。

    **两个尺寸都必须显式写死**（`h-[22px]` + `w-[132px]`），都不能靠内容撑：
      * `w` 写死是为了不随文案变（见上）；
      * `h` 写死是因为唯一的子元素是 `absolute inset-0` ——
        **绝对定位元素不参与父级高度计算**，胶囊会塌成
        `padding + border` = 6px 高，17px 的文字整个溢出去、
        上下边框线压在字上。不写 `h` 就是这个结果（实测过）。

    h-[22px] 的来历：内容高 17px（11px 字号 × line-height 1.5）
    + 上下各 2.5px 内边距 = 22。标题栏高 36px，居中后上下各留 7px。

    **不要给文字加 `truncate`**：宽度既然够宽，切字只会在超长异常文案时
    发生，那时应该看到完整的错误信息而不是被切掉一半。
    改尺寸前先用 `probe_capsule_width.py` / `probe_capsule_height.py`
    （canvas measureText 与 getBoundingClientRect 实测）核对，别凭感觉调。 */

/**
 * 结果态图标：出错用警示三角，成功用对勾，检查中用旋转箭头。
 * 三种状态光靠文字区分不够 —— 「已是最新」与「检查失败」在 11px 下
 * 长度接近，图标是唯一可靠的第二通道。
 */
const capsuleIcon = computed(() => {
  if (props.checkingUpdate) return RefreshCw;
  if (props.updateNotice) return props.updateNoticeError ? AlertTriangle : Check;
  return Users;
});

/** 检查中的胶囊要转菊花；结果态静止，否则 3 秒后提示消失时图标还在转 */
const capsuleSpinning = computed(() => props.checkingUpdate);

onMounted(async () => {
  await syncMaximized();
  // 监听窗口尺寸变化：用户拖边缘、双击标题栏、Win+↑、Snappy 贴靠都会改状态，
  // 只在按钮点击后同步会让图标与实际状态脱节
  unlistenResize = await win.onResized(() => {
    void syncMaximized();
  });
  void getVersion()
    .then((v) => {
      version.value = `v${v}`;
    })
    .catch(() => {
      // 非 Tauri 环境（dev server 直开）取不到版本，留空即可
    });
});

onUnmounted(() => {
  unlistenResize?.();
});

/**
 * 胶囊内容的进出动画（图标 + 文字整组）。
 *
 * 用默认的并发模式而非 out-in：串行模式要求旧内容走完 leave 才进新内容，
 * 而检查更新在本地包上瞬间返回，等 leave 结束时结果已就位，
 * 「正在检查…」那一帧根本不会被渲染 —— 用户看到的是「按了没反应，直接
 * 变成结果」。并发模式下新旧重叠存在，整个切换过程都看得见。
 *
 * 胶囊外层加 position: relative 是并发的必要条件：重叠的两个元素在
 * 普通文档流里会各占一行，把胶囊撑高一倍。绝对定位后它们叠在同一处。
 *
 * 动画只做位移 + 淡入淡出，不做弹跳 —— 标题栏是常驻区域，弹跳会持续
 * 干扰视线。reduced-motion 下 style.css 会把时长压到 0.001ms 整体关掉。
 *
 * 六个 key 必须是 `enterFromClass` / `leaveToClass` 这种**带 Class 后缀**的
 * 全名，漏掉后缀会让整组动画静默失效：
 *   * Vue 3 的 `<Transition>` 只声明 enterFromClass / enterActiveClass /
 *     enterToClass 与 leaveFromClass / leaveActiveClass / leaveToClass
 *     （见 node_modules/@vue/runtime-dom 的 DOMTransitionPropsValidators）；
 *   * Vue 2 的对应名字是 `enterClass` / `leaveClass`，**从来不是**
 *     `enterFrom` / `leaveFrom` —— 中间那个状态在 Vue 2 里叫 enter，
 *     所以凭直觉写出的 `enterFrom` 两边都不合法；
 *   * 写错不抛异常、不打警告：这些 key 被当作普通 attr 落到子元素上，
 *     渲染成 `enterfrom="translate-y-1 opacity-0"` 这样的非法属性，
 *     而 Vue 自己改用默认的 `v-enter-from` —— 项目 CSS 里没有这个类，
 *     于是过渡变成空操作，不透明度恒为 1、时长读出 0。
 *     症状与「类名没被 Tailwind 扫到」完全一样，靠读代码分辨不出来。
 */
const capsuleAnim = {
  enterFromClass: "translate-y-1 opacity-0",
  enterActiveClass: "transition duration-300 ease-out",
  enterToClass: "translate-y-0 opacity-100",
  leaveFromClass: "translate-y-0 opacity-100",
  leaveActiveClass: "transition duration-200 ease-in",
  leaveToClass: "-translate-y-1 opacity-0",
};
</script>

<template>
  <!-- 拖拽区是整条标题栏，而不是只有标题那几个字。
       wry 按「鼠标落在哪个元素的哪个像素」决定是否接管拖拽，
       只给标题文字加 data-tauri-drag-region 的话，标题两侧的空白
       按下时窗口不会动，用户会以为那部分不可拖。
       不可拖的元素（状态胶囊、窗口按钮）各自标
       data-tauri-drag-region="false" 局部排除。 -->
  <header
    class="flex h-9 shrink-0 items-center gap-2 select-none
           border-b border-border bg-background pl-3 pr-0"
    data-tauri-drag-region
    @dblclick="onDragRegionDblClick"
  >
    <!-- 左：图标 + 名称 + 版本号 -->
    <div class="flex items-center gap-2" data-tauri-drag-region>
      <!-- 标题栏图标。**与 exe / 任务栏 / 资源管理器同源**：
           直接引用 `tauri icon` 生成的图标集里的一帧，因此任务管理器、
           资源管理器、任务栏与这条标题栏看到的永远是同一张图。
           `pnpm tauri icon img/app.ico` 重生成图标集后，标题栏自动跟随，
           不存在「两处图标不一致」的可能 —— 这正是本文件此前维护一份
           独立 PNG 副本时反复出问题的根源（改了一处忘了另一处）。

           定位说明：必须用应用图标本身，不能用 lucide 的通用图形（原先是 Box）——
           decorations:false 下这条标题栏是整个窗口唯一的 branding 位，
           通用图标会被读成「程序没找到自己的图标」。

           尺寸 h-6（24px）而不是 h-4（16px）：16px 下圆环与雪佛龙糊成一团，
           用户实测「根本看不到」。标题栏高 36px，上下各留 6px。
           alt 留空 + aria-hidden —— 窗口标题已经承担了语义，图标只是视觉锚点。 -->
      <img
        :src="appIcon"
        class="h-6 w-6 shrink-0 select-none"
        alt=""
        aria-hidden="true"
        draggable="false"
      />
      <span class="text-[13px] font-semibold" data-tauri-drag-region>
        守望先锋直播掉宝助手
      </span>
      <span
        v-if="version"
        class="text-[11px] tabular-nums text-muted-foreground"
        data-tauri-drag-region
      >
        {{ version }}
      </span>
    </div>

    <!-- 中：全局状态胶囊。容器自身是拖拽区（撑开标题栏中段的空白），
         只有胶囊本体标false 排除 —— 用户框出的两段「按了不动」的空白
         正是这个容器此前漏标data-tauri-drag-region 造成的。

         胶囊同时承载「检查更新」的结果提示：检查中显示旋转箭头 +
         「正在检查…」，出结果后换成对勾/警示三角 + 结论文案，3 秒后
         提示清空、自动退回运行状态。选这个位置是因为它是标题栏里
         唯一不承载操作的视觉位，且横向居中天然抢到视线。 -->
    <div class="flex flex-1 items-center justify-center" data-tauri-drag-region>
      <span
        data-tauri-drag-region="false"
        class="pointer-events-none relative inline-flex h-[22px] w-[132px]
               shrink-0 items-center justify-center gap-1.5 rounded-full
               border px-2.5 text-[11px] leading-none
               transition-colors duration-300"
        :class="updateNotice && updateNoticeError
          ? 'border-signal-danger/40 bg-signal-danger/10 text-signal-danger'
          : updateNotice
            ? 'border-signal-success/40 bg-signal-success/10 text-signal-success'
            : 'border-border bg-muted/60 text-muted-foreground'"
        :title="capsuleText"
        role="status"
        aria-live="polite"
      >
        <!-- 图标与文字必须放在**同一个** <Transition> 里：
             两个独立 Transition 各播各的，时序无法对齐，会出现
             「新文字配旧图标」的错帧。而且 key 要绑在整组内容上 ——
             同一节点换文本不触发 Transition，必须靠 key 变化让 Vue 重挂载。

             不用 mode="out-in"：它要求旧元素走完 leave（100ms）才进新元素，
             而检查更新在本地包上瞬间返回（后端不发网络请求），等 leave
             结束时结果文案已就位，「正在检查…」那一帧根本不会被渲染。
             并发进出（默认模式）让新旧重叠切换，反而看得见过程。 -->
        <Transition v-bind="capsuleAnim">
          <span
            :key="capsuleText"
            class="absolute inset-0 flex items-center justify-center gap-1.5"
          >
            <component
              :is="capsuleIcon"
              class="h-3 w-3 shrink-0"
              :class="[
                capsuleSpinning ? 'animate-spin' : '',
                !updateNotice && runningCount > 0 ? 'text-signal-success' : '',
              ]"
              aria-hidden="true"
            />
            <!-- 不要加 truncate：胶囊固定 132px（见上面的宽度注释），
                 常见文案都装得下；加 truncate 只会让超长异常文案被首尾切掉，
                 而那种情况下用户需要的恰恰是完整的错误信息。 -->
            <span class="max-w-[110px]">{{ capsuleText }}</span>
          </span>
        </Transition>
      </span>
    </div>

    <!-- 右：检查更新 + 主题切换 + 窗口三键。窗口键宽度 44px 与
         Windows 11 原生一致，便于肌肉记忆。

         「检查更新」放在主题按钮**左侧**而不是最右：窗口键是高频误触区
         （用户想点关闭时容易偏一格），把低频的检查按钮隔在主题按钮外侧
         多了一道缓冲。 -->
    <div class="flex shrink-0 items-center" data-tauri-drag-region="false">
      <button
        type="button"
        class="flex h-9 w-9 items-center justify-center text-muted-foreground
               transition-colors hover:bg-accent hover:text-foreground
               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring
               disabled:pointer-events-none disabled:opacity-50"
        :disabled="checkingUpdate"
        aria-label="检查更新"
        title="检查更新"
        @click="emit('check-update')"
      >
        <RefreshCw
          class="h-4 w-4"
          :class="checkingUpdate ? 'animate-spin' : ''"
          aria-hidden="true"
        />
      </button>
      <button
        type="button"
        class="flex h-9 w-9 items-center justify-center text-muted-foreground
               transition-colors hover:bg-accent hover:text-foreground
               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        :aria-label="dark ? '切换到浅色主题' : '切换到深色主题'"
        :title="dark ? '切换到浅色主题' : '切换到深色主题'"
        @click="emit('toggle-theme')"
      >
        <Sun v-if="dark" class="h-4 w-4" aria-hidden="true" />
        <Moon v-else class="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-9 w-11 items-center justify-center text-muted-foreground
               transition-colors hover:bg-accent hover:text-foreground
               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        aria-label="最小化"
        title="最小化"
        @click="minimize"
      >
        <Minus class="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-9 w-11 items-center justify-center text-muted-foreground
               transition-colors hover:bg-accent hover:text-foreground
               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        :aria-label="isMaximized ? '还原' : '最大化'"
        :title="isMaximized ? '还原' : '最大化'"
        @click="toggleMaximize"
      >
        <Copy v-if="isMaximized" class="h-3.5 w-3.5" aria-hidden="true" />
        <Square v-else class="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-9 w-11 items-center justify-center text-muted-foreground
               transition-colors hover:bg-destructive hover:text-destructive-foreground
               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        aria-label="关闭"
        title="关闭"
        @click="close"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  </header>
</template>