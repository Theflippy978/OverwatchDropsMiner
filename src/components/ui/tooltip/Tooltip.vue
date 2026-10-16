<script setup lang="ts">
/** 自绘 Tooltip（替换原生 title，全局唯一入口）。
 *
 *  为什么不用原生 title：它是浏览器绘制的 —— 深色系统气泡、不跟随应用主题、
 *  约 1s 固定延迟、无进出场动画、键盘聚焦也不触发。这与本项目所有浮层
 *  （对话框 / 下拉菜单 / 右键菜单 / Select）都用 --popover 令牌自绘的风格冲突。
 *
 *  这里包 reka-ui 的 Tooltip 原语（shadcn-vue 官方 Tooltip 的同一底座）：
 *  主题配色、定位、延迟、aria-describedby 绑定都由 reka 负责，本层只固定
 *  三件项目级规定（用户 2026-10-14 拍板）：
 *    * 向下弹出（side=bottom；空间不足时 reka 仍会 smart flip，不强制越界）；
 *    * --popover 配色（与 popover 家族同族，深浅色自动跟随）；
 *    * 700ms 延迟（reka 默认，快速扫过界面不误弹）。
 */
import {
  TooltipContent,
  TooltipPortal,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
} from "reka-ui";
import { cn } from "@/lib/utils";

const props = withDefaults(
  defineProps<{
    /** tooltip 文字。空串时整条 tooltip 不渲染（复刻原生 title 为空即不显示的行为，
     *  调用方不必自己判空 —— 直接把可能为空的表达式传进来即可）。 */
    label: string;
    /** 触发元素是 disabled（如「检查更新」进行中、未选账号时的领取键）时传 true。
     *  disabled 元素不派发 pointer 事件，as-child 把 hover 直接绑在它身上会让
     *  tooltip 静默不出现 —— 这正是原生 title 能显示在灰按钮上、而默认做不到的地方。
     *  传 true 时用一层 inline-flex span 承载 trigger，让 hover 落在 span 上。 */
    wrap?: boolean;
    /** 内容对齐。短标签居中即可；上百字的长帮助文字传 "start" 左对齐更易读。 */
    align?: "start" | "center" | "end";
  }>(),
  { wrap: false, align: "center" },
);
</script>

<template>
  <TooltipProvider v-if="label" :delay-duration="700">
    <TooltipRoot>
      <TooltipTrigger v-if="!wrap" as-child>
        <slot />
      </TooltipTrigger>
      <TooltipTrigger v-else as="span" class="inline-flex">
        <slot />
      </TooltipTrigger>
      <TooltipPortal>
        <!-- 进出场引用 --duration-fast / --ease-enter|exit token，与 DialogContent、
             Select 浮层同源（缺 token 会退回 tw-animate-css 的默认 ease 关键字，
             与项目「进入用 ease-enter、退出用 ease-exit」不一致）。
             不加 TooltipArrow：全项目浮层（对话框/下拉/右键菜单/Select）都无箭头，
             单给 tooltip 加反而不成一族；且箭头要设 --reka-tooltip-arrow-fill
             跟边框色，多一个会漂移的配色点。 -->
        <TooltipContent
          side="bottom"
          :align="props.align"
          :side-offset="6"
          :class="
            cn(
              'z-50 max-w-64 break-words rounded-md border bg-popover px-2.5 py-1.5',
              'text-xs text-popover-foreground shadow-md',
              'duration-[var(--duration-fast)] ease-[var(--ease-enter)]',
              'data-[state=closed]:ease-[var(--ease-exit)]',
              // 开态有两种：delayed-open（首次悬停，走了 700ms 延迟）与
              // instant-open（连续移到下一个，跳过延迟）。只写 delayed-open
              // 会让「第二个及以后」的 tooltip 瞬时出现、没有动画。
              'data-[state=delayed-open]:animate-in data-[state=instant-open]:animate-in',
              'data-[state=delayed-open]:fade-in-0 data-[state=instant-open]:fade-in-0',
              'data-[state=delayed-open]:zoom-in-95 data-[state=instant-open]:zoom-in-95',
              'data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95',
              'data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2',
              // 退出位移与 Select.vue / DropdownMenuContent 完全同一约定
              // （bottom 档「进 from-top、出 to-bottom」向外扩散，幅度同为 2）：
              // 有 in 就必须有 out（同 DropdownMenuContent 踩过的坑：只有 in 没有 out
              // 时弹出来有来处、消失却凭空没了）。
              'data-[side=bottom]:slide-out-to-bottom-2 data-[side=top]:slide-out-to-top-2',
            )
          "
        >
          {{ label }}
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
  <!-- label 为空：原样渲染触发元素，不套任何 provider（零开销、也不产生 role="tooltip"） -->
  <slot v-else />
</template>
