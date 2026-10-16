<script setup lang="ts">
import type { DropdownMenuContentEmits, DropdownMenuContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import {
  DropdownMenuContent,
  DropdownMenuPortal,
  useForwardPropsEmits,
} from "reka-ui"
import { cn } from "@/lib/utils"

const props = withDefaults(
  defineProps<DropdownMenuContentProps & { class?: HTMLAttributes["class"] }>(),
  {
    sideOffset: 4,
  },
)
const emits = defineEmits<DropdownMenuContentEmits>()

const delegatedProps = reactiveOmit(props, "class")

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <DropdownMenuPortal>
    <!-- 菜单类浮层用 150ms（--duration-fast）而不是对话框的 220ms：
         菜单是高频轻量操作，慢一拍就会显得迟钝；对话框是模态打断，
         稍慢反而更稳。时长不同是有依据的，但**缓动必须同源** ——
         原先这里连时长都没写，走的是 tw-animate-css 的默认 150ms + CSS
         关键字 ease。现在时长与缓动都显式引用项目 token。 -->
    <DropdownMenuContent
      v-bind="forwarded"
      :class="cn('z-50 min-w-32 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md duration-[var(--duration-fast)] ease-[var(--ease-enter)] data-[state=closed]:ease-[var(--ease-exit)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-[side=bottom]:slide-out-to-bottom-2 data-[side=left]:slide-out-to-left-2 data-[side=right]:slide-out-to-right-2 data-[side=top]:slide-out-to-top-2', props.class)"
    >
      <slot />
    </DropdownMenuContent>
  </DropdownMenuPortal>
</template>
