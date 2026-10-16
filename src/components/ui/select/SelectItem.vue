<script setup lang="ts">
import { computed } from "vue";
import type { HTMLAttributes } from "vue";
import type { SelectItemProps } from "reka-ui";
import { Check } from "lucide-vue-next";
import {
  SelectItem as RekaSelectItem,
  SelectItemIndicator,
  SelectItemText,
} from "reka-ui";
import { cn } from "@/lib/utils";
import { normalizeSelectValue } from "./constants";

const props = defineProps<SelectItemProps & { class?: HTMLAttributes["class"] }>();

// class 必须从转发对象里剔除：下面的 :class 已经把它并进 cn() 了。
// 不剔的话 Vue 会同时应用 v-bind 的 class 与 :class，同一串类名出现两次。
const { class: _class, ...rest } = props;
const forwarded = computed(() => ({
  ...rest,
  value: normalizeSelectValue(props.value),
}));
</script>

<template>
  <RekaSelectItem
    v-bind="forwarded"
    :class="
      cn(
        'relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-7 pr-2 text-xs outline-none',
        'transition-colors data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground',
        'data-[state=checked]:font-medium data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        props.class,
      )
    "
  >
    <!-- 对勾用绝对定位、不占位：否则每项都要让出一个图标宽度，
         选「全部账号」时第一项前面的空隙会和其他项对不上。 -->
    <span class="absolute left-1.5 flex h-3.5 w-3.5 items-center justify-center">
      <SelectItemIndicator>
        <Check class="h-3 w-3" />
      </SelectItemIndicator>
    </span>
    <SelectItemText>
      <slot />
    </SelectItemText>
  </RekaSelectItem>
</template>
