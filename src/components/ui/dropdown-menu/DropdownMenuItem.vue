<script setup lang="ts">
import type { DropdownMenuItemProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { DropdownMenuItem, useForwardProps } from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<DropdownMenuItemProps & { class?: HTMLAttributes["class"], inset?: boolean }>()

// inset 是本组件自己声明的 prop（用于下方的 pl-8），必须一并从转发对象里
// 剔除：reactiveOmit 只剔 class 时，inset 会经 Primitive 落到 DOM 上，
// 渲染成非法属性 `inset="true"`。
const delegatedProps = reactiveOmit(props, "class", "inset")

const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
  <DropdownMenuItem
    v-bind="forwardedProps"
    :class="cn(
      'relative flex cursor-default select-none items-center rounded-sm gap-2 px-2 py-1.5 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&>svg]:size-4 [&>svg]:shrink-0',
      inset && 'pl-8',
      props.class,
    )"
  >
    <slot />
  </DropdownMenuItem>
</template>
