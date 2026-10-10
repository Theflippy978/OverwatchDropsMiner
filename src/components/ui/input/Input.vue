<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { useVModel } from "@vueuse/core"
import { cn } from "@/lib/utils"

const props = defineProps<{
  defaultValue?: string | number
  modelValue?: string | number
  class?: HTMLAttributes["class"]
}>()

const emits = defineEmits<{
  (e: "update:modelValue", payload: string | number): void
}>()

const modelValue = useVModel(props, "modelValue", emits, {
  passive: true,
  defaultValue: props.defaultValue,
})
</script>

<template>
  <!-- 默认高度保留 shadcn 的 h-10（40px）。
       **不要**为了「消除默认值被覆盖」而改成 h-8：本项目有 2 处调用
       （AccountList 的 Cookie 输入框与备注输入框）**没有**传高度类，
       它们依赖的正是这个 h-10 默认值 —— 改成 h-8 会把两个对话框里的
       输入框从 40px 悄悄压到 32px，属于引入视觉回归。
       ConfigForm 的 6 处传了 h-8，那是密集表单的局部选择，两者并存是合理的。

       hover:border-ring：Button 有 hover 反馈而输入框此前完全没有，
       鼠标划过时没有任何「可交互」的暗示。只改边框色，不改尺寸，
       因此不会引起布局位移。

       file:* 六个伪类已删除：本项目没有任何文件上传输入框，
       它们是 shadcn 模板带来的死代码。 -->
  <input v-model="modelValue" :class="cn('flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background transition-colors placeholder:text-muted-foreground hover:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', props.class)">
</template>
