<script setup lang="ts">
import type { ProgressRootProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import {
  ProgressIndicator,
  ProgressRoot,
} from "reka-ui"
import { cn } from "@/lib/utils"

/**
 * 可访问名称。reka 的 `getValueLabel` 默认实现是
 * `(value, max) => `${Math.round(value / max * 100)}%``，而它被绑到
 * **`aria-label`**（可访问名称）上 —— 于是读屏把进度条念成「42%」，
 * 听起来像一个没有名字的控件。名称应回答「这是什么」，值才是「多少」。
 *
 * 实测（headless Chromium 挂载真实组件，读渲染后的 DOM）：
 *   只传 modelValue        → aria-label="42%"   ← 问题所在
 *   传 getValueLabel       → aria-label="任务进度"
 *   同时传 getValueText    → aria-label="任务进度" + aria-valuetext="42 / 100"
 * 后者最完整，故两个都提供。
 *
 * 用 getValueLabel/getValueText 而不是外部传 `aria-label`：两者实测都能
 * 覆盖，但前者是 reka 的公开 API，不依赖 attr 合并的优先级规则。
 *
 * **`getValueText` 的 `value == null` 分支在当前用法下不可达**（如实记录，
 * 不要以为它是一层有效防御）：下面的 `withDefaults` 把 `modelValue` 默认
 * 设为 **0**（不是 null/undefined），而唯一调用点 TaskProgress 传的是
 * `percentOf(task)` —— `Math.floor` 后的 number，`target <= 0` 时返回 0。
 * 所以真实路径上 `value` 永远是 number，`aria-valuetext` 恒有值
 * （例如 `"0 / 100"`）。
 *
 * 保留该分支是为了**调用方显式传 `null`**（reka 用 null 表示
 * indeterminate 进度条）时不渲染出 `"null / 100"` 这种文案。
 * 但若将来有人把默认值改成 `undefined`，未传值的进度条会整体变成
 * indeterminate 状态（指示条不再受 modelValue 控制）—— 那是有意的
 * 行为变更，不是「让空值分支可达」的顺手修正。
 */
const props = withDefaults(
  defineProps<
    ProgressRootProps & {
      class?: HTMLAttributes["class"]
      /** 可访问名称。默认「任务进度」—— 调用方若有更精确的说法可覆盖。 */
      label?: string
    }
  >(),
  {
    modelValue: 0,
    label: "任务进度",
  },
)

const delegatedProps = reactiveOmit(props, "class", "label")
</script>

<template>
  <ProgressRoot
    v-bind="delegatedProps"
    :get-value-label="() => props.label"
    :get-value-text="(value: number | null | undefined, max: number) => value == null ? undefined : `${value} / ${max}`"
    :class="
      cn(
        'relative h-4 w-full overflow-hidden rounded-full bg-secondary',
        props.class,
      )
    "
  >
    <!-- transition-transform 而不是 transition-all：
         all 会过渡**所有**可过渡属性。当前只改 transform 所以暂时无碍，
         但一旦有人给它加 height/width/margin 或让它参与 flex 伸缩，
         就会立刻引入布局过渡 —— 正是本项目反复吃过的「布局抖动」那类缺陷。
         写死 transform 把风险按在源头。

         时长用 --duration-normal（220ms）而不是 --duration-slow：
         原先 transition-all 走的是 Tailwind 默认 0.15s，改成 slow（400ms）
         会让这条进度条比改前慢 2.7 倍 —— 那是**改变观感**，超出「token 收口」
         的范围。220ms 最接近原值，同时仍受 token 统一管理。
         （同卡内手写的「掉宝进度」条用的是 slow，两者语义不同：
         那条是「整体掉宝进度」的主指标，变化幅度大、慢一点更易读。） -->
    <ProgressIndicator
      class="h-full w-full flex-1 bg-primary transition-transform duration-[var(--duration-normal)] ease-[var(--ease-inout)]"
      :style="`transform: translateX(-${100 - (props.modelValue ?? 0)}%);`"
    />
  </ProgressRoot>
</template>
