<script setup lang="ts">
import { computed, useAttrs } from "vue";
import type { HTMLAttributes } from "vue";
import type { SelectRootProps } from "reka-ui";
import { ChevronDown } from "lucide-vue-next";
import {
  SelectContent,
  SelectIcon,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
} from "reka-ui";
import { cn } from "@/lib/utils";
import { denormalizeSelectValue, normalizeSelectValue } from "./constants";

defineOptions({ inheritAttrs: false });

const props = defineProps<
  SelectRootProps & {
    class?: HTMLAttributes["class"];
  }
>();

const attrs = useAttrs();

// modelValue 不能整包 v-bind="$attrs" 透传：Root 与 Item 必须走同一个
// 归一化（见 ./constants.ts），否则选中态永远对不上账。
const normalizedModelValue = computed(() => normalizeSelectValue(props.modelValue));

/** 回传给调用方的值必须反归一（见 ./constants.ts 里 denormalizeSelectValue 的说明）。
 *  调用方的 handler 在 attrs 里（本组件没声明 emits），可能是函数或函数数组。 */
function emitModelValue(value: unknown) {
  const handler = attrs["onUpdate:modelValue"] as
    | ((v: unknown) => void)
    | ((v: unknown) => void)[]
    | undefined;
  const denormalized = denormalizeSelectValue(value);
  if (Array.isArray(handler)) handler.forEach((fn) => fn?.(denormalized));
  else handler?.(denormalized);
}

/** 落到真正渲染出来的那个 button 上。
 *
 *  为什么不在 Root 上 `v-bind="$attrs"`：reka 的 SelectRoot 与它渲染的
 *  PopperRoot **都是 `inheritAttrs: false` 且只 renderSlot**，属性走到 Root
 *  就被静默丢弃 —— `id` / `aria-label` / `data-*` / 原生事件一个都到不了 DOM，
 *  读屏用户对着一个没有名字的 combobox（原先的原生 select 有）。
 *  这里改绑 Trigger（Primitive 用 `h(as, attrs)` 展开，属性真落在 button 上）。
 *
 *  陷阱：本组件的 props 已把 Root 的全部字段（open / disabled / name / required /
 *  multiple / autocomplete / dir / by / nullableValue）声明掉了，所以它们**不在
 *  attrs 里、也没往 Root 传** —— 想支持 `:disabled` 得显式绑到 SelectRoot 上，
 *  别指望它自动生效（现无任何调用方传这些，故不预先加转发）。 */
const triggerAttrs = computed(() => {
  const { "onUpdate:modelValue": _handler, ...rest } = attrs as Record<string, unknown>;
  return rest;
});
</script>

<template>
  <SelectRoot :model-value="normalizedModelValue" @update:model-value="emitModelValue">
    <SelectTrigger
      v-bind="triggerAttrs"
      :class="
        cn(
          // 与原生 select 同高（h-7 / text-xs），换过来不改变日志卡头的行高
          // 宽度跟内容（w-fit）而不是 w-full：本组件出现在 flex 行内，
          // w-full 会抢满剩余空间，再由 justify-between 把文字与箭头
          // 分推到两端 —— 文字短时中间空出一大块（用户报过）。
          // 也不要 justify-between：文字与箭头该紧贴，留白应只在右侧。
          'flex h-7 w-fit items-center rounded-md border border-input',
          'bg-background pl-2.5 pr-1.5 text-xs transition-colors hover:border-ring',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          // 展开态给一圈 ring：reka 的 Content 不跟随 Trigger 一起高亮，
          // 没有它的话「菜单展开了、触发器却和收起时一样」，容易看不出当前焦点在哪。
          'data-[state=open]:border-ring data-[state=open]:ring-2 data-[state=open]:ring-ring/40',
          'data-[placeholder]:text-muted-foreground',
          // 箭头旋转：**必须挂在 Trigger 上用后代选择器**，不能挂在 SelectIcon
          // 自己的类上 —— reka 的 `data-state` 只设在 Trigger（Primitive 渲染的
          // button）上，SelectIcon 渲染出的 span 没有这个属性，
          // 「展开时旋转 180 度」那条工具类写在它身上永远不命中
          // （2026-10-14 用户实测「箭头展开时没有旋转」即此）。
          '[&_svg]:transition-transform [&_svg]:duration-[var(--duration-fast)] [&_svg]:ease-[var(--ease-inout)] data-[state=open]:[&_svg]:rotate-180',
          props.class,
        )
      "
    >
      <!-- min-w-0 + truncate：flex 子项默认 min-width:auto，长文案会把
           触发器撑宽而不是截断。 -->
      <SelectValue class="min-w-0 truncate" />
      <!-- 旋转由上面 Trigger 类里的 [&_svg] 规则驱动，这里不再挂 data-state 类 -->
      <SelectIcon class="shrink-0 text-muted-foreground">
        <ChevronDown class="h-3 w-3" />
      </SelectIcon>
    </SelectTrigger>
    <SelectPortal>
      <!-- side="top" 固定往上弹（用户 2026-10-14 要求）：调用方在日志卡头，
           那里贴着窗口底部，浮层朝下会吃掉大量视口、也更容易被 max-h-72 截断。
           注意 reka 的 side 只是**首选**方位，空间不足时仍会 flip；
           上面那组 data-[side=*] 的滑入方向因此不能删 —— 它按实际方位生效。

           ⚠ 这段注释**必须留在标签外面**：把注释写进标签的属性列表中间
           （属性与属性之间），类型检查会返回 0、静态门禁也全绿 ——
           因为它们都不编译模板；只有真正构建才炸
           （`[builtin:vite-transform] Invalid Character`，2026-10-14 踩过）。
           另：注释正文里不要出现注释的闭合标记字符 —— 它会提前闭合本条注释，
           剩下的文字变成模板正文被渲染出来（2026-10-14 就把自己举的这个例子
           写了进去，结果这行说明连同后半句直接显示在界面上）。 -->
      <SelectContent
        :class="
          cn(
            'z-50 max-h-72 min-w-32 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md',
            // 时长与缓动引用项目 token，与 DialogContent / DropdownMenuContent 同源
            'duration-[var(--duration-fast)] ease-[var(--ease-enter)]',
            'data-[state=closed]:ease-[var(--ease-exit)]',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2',
            'data-[side=bottom]:slide-out-to-bottom-2 data-[side=left]:slide-out-to-left-2 data-[side=right]:slide-out-to-right-2 data-[side=top]:slide-out-to-top-2',
          )
        "
        position="popper"
        side="top"
        :side-offset="4"
      >
        <div class="scroll-subtle max-h-64 overflow-y-auto">
          <slot />
        </div>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
