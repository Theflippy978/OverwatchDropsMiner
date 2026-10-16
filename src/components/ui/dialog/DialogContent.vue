<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { X } from "lucide-vue-next"
import {
  DialogClose,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  useForwardPropsEmits,
} from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<
  DialogContentProps & {
    class?: HTMLAttributes["class"]
    /** 是否渲染右上角关闭按钮。异步操作进行中应传 false：
        否则 ESC / 遮罩 / X 仍能关掉对话框，而按钮已 disabled，
        状态自相矛盾 —— 用户以为「不能点了」却能把对话框关掉，
        后台操作继续跑完且没有任何完成反馈。 */
    showClose?: boolean
  }
>()
const emits = defineEmits<DialogContentEmits>()

const delegatedProps = reactiveOmit(props, ["class", "showClose"])

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <DialogPortal>
    <!-- 遮罩比内容略快（150ms vs 220ms）是刻意的层次：遮罩先就位，
         内容再落上去，观感上像「内容落在已有的暗底上」而不是两者一起淡入。
         这里补的是时长与缓动来源 —— 原先两者都走 tw-animate-css 的默认值
         （150ms + CSS 关键字 ease），现在统一引用项目 token。 -->
    <DialogOverlay
      class="fixed inset-0 z-50 bg-overlay duration-[var(--duration-fast)] ease-[var(--ease-inout)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
    />
    <DialogContent
      v-bind="forwarded"
      :class="
        cn(
          // 进场只做「从中心淡入 + 轻微放大」，不做位移。
          // 原来的写法是「从左半宽处横向滑入 + 从 48% 高度处纵向滑入」，
          // 会把弹窗从左上角斜滑进来 —— 终点虽是中心，视觉上却像
          // 从窗口左上角飞过去，与「点按钮弹出对话框」的直觉相反。
          // 位移还叠加了 -translate-x-1/2 的定位补偿，两者相加后
          // 起点偏移量难以准确预测，改文案时极易调不准。
          //
          // **本条注释刻意不复写那两个旧类名**：Tailwind v4 按源码原始文本
          // 扫描，注释里出现的类名会被当真生成进产物 CSS —— 实测这两个
          // 类名在产物里真的各生成了一条规则（而 class 属性里零使用），
          // 属死规则。
          // 缓动也收口到 token：tw-animate-css 的进出场动画默认走 CSS 关键字
          // ease，与项目的「进入用 ease-enter、退出用 ease-exit」不一致。
          // 它读的是 --tw-ease 变量，所以 Tailwind 的缓动工具类能接管；
          // 进出场要分别给，同一个元素上缓动是单向的。
          'fixed left-1/2 top-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 border bg-background p-6 shadow-lg duration-[var(--duration-normal)] ease-[var(--ease-enter)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:ease-[var(--ease-exit)] data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 sm:rounded-lg',
          props.class,
        )"
    >
      <slot />

      <DialogClose
        v-if="showClose !== false"
        class="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground"
      >
        <X class="w-4 h-4" />
        <span class="sr-only">关闭</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
