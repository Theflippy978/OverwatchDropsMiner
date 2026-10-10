<script setup lang="ts">
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const labelVariants = cva(
  "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
);

interface Props {
  for?: string;
  class?: string;
}

const props = defineProps<Props>();
</script>

<template>
  <!-- 必须走 cn（twMerge）而不是 labelVariants({ class })：
       cva 在没有定义 variants 时不做合并，`{ class: ... }` 只是把调用方的类
       追加到基础类之后。于是调用方传 class="text-xs" 时产物里会同时出现
       `text-sm` 与 `text-xs` 两个 font-size 类，谁生效完全取决于 Tailwind
       在产物 CSS 里的声明顺序（当前 .text-sm 在前、.text-xs 在后，所以
       text-xs 侥幸胜出）—— 一旦排序策略变化或有人调整类名，字号就会
       静默回退成 text-sm，而没有任何报错。
       cn 会做 twMerge，同类属性只保留后者，行为确定。 -->
  <label
    :for="props.for"
    :class="cn(labelVariants(), props.class)"
  >
    <slot />
  </label>
</template>
