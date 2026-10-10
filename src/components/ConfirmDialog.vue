<script setup lang="ts">
import { computed } from "vue";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
  loading?: boolean;
  /** loading 期间确认按钮的文案。默认「处理中…」。
   *
   *  这是**唯一的加载态视觉反馈**（本组件刻意不用 spinner 图标，
   *  理由见模板里确认按钮上方的长注释：图标无论怎么摆都会留下
   *  占位空位或宽度突变，而用户明确反馈过「删除按钮出现前导空位」）。
   *  调用方若知道具体动作，可传更精确的文案（如「删除中…」）。 */
  loadingText?: string;
  /** 单按钮提示场景可隐藏取消按钮（例如“无法关闭”提示） */
  showCancel?: boolean;
  /** 操作失败的原因。确认类操作失败时提示必须显示在框内：
      弹窗打开期间页面上的错误条被全屏遮罩盖住，用户看不到任何反馈，
      只会认为程序卡死或按钮没生效。 */
  error?: string;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  confirm: [];
  cancel: [];
}>();

const isOpen = computed({
  get: () => props.open,
  set: (value) => emit("update:open", value),
});

const confirmButtonVariant = computed(() => props.variant ?? "default");

/**
 * loading 期间拦截 ESC / 点遮罩两条关闭路径。
 *
 * **不能用 `:close-on-escape-key-down` / `:close-on-click-outside`** ——
 * 这两个 prop 在 reka-ui 2.10.5 里根本不存在（对 node_modules/reka-ui/dist
 * 递归 grep 两者均 0 命中；DialogContentImpl 的真实 props 只有
 * forceMount / trapFocus / disableOutsidePointerEvents / asChild / as / present）。
 * 写上去只会变成 DOM 上的非法属性，关闭保护**完全不存在**，且不报错不警告：
 * 用户点「删除」看到按钮变灰、转圈，以为「正在删且不能取消」，
 * 此时按 ESC 或点遮罩对话框照常关闭 —— 而 stop_miner + remove_account
 * 会继续跑完并真的删掉账号。这是不可逆操作，必须真正拦住。
 *
 * 正确做法是监听 reka 真正 emit 的事件并 preventDefault。
 * DismissableLayer 的实现是（dist/DismissableLayer/DismissableLayer.js）：
 *     emits("escapeKeyDown", event);
 *     if (!event.defaultPrevented) emits("dismiss");
 * 即事件先 emit 给使用方，只有未被 preventDefault 才继续 dismiss —— 所以
 * 在回调里 preventDefault() 就能拦住关闭。
 *
 * X 按钮走 showClose（本项目自定义的 prop，DialogContent.vue 里 v-if 控制），
 * 是第三条独立路径，由 `:show-close="!loading"` 负责。 */
function onBlockClose(event: Event) {
  if (props.loading) event.preventDefault();
}
</script>

<template>
  <Dialog v-model:open="isOpen">
    <!-- loading 期间禁掉 ESC / 遮罩 / X 三条关闭路径：
         删除账号是「stop_miner + remove_account」多步长耗时操作，
         中途关掉对话框会让用户失去「我再想想」的机会，
         而操作仍会跑完并真的删掉账号。按键已 disabled 却能关窗属自相矛盾。 -->
    <DialogContent
      class="sm:max-w-md"
      :show-close="!loading"
      @escape-key-down="onBlockClose"
      @interact-outside="onBlockClose"
    >
      <DialogHeader>
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription>{{ message }}</DialogDescription>
      </DialogHeader>

      <p
        v-if="error"
        class="break-all text-sm text-signal-danger"
        role="alert"
      >
        {{ error }}
      </p>

      <DialogFooter>
        <Button
          v-if="showCancel !== false"
          variant="outline"
          :disabled="loading"
          @click="emit('cancel')"
        >
          {{ cancelText ?? "取消" }}
        </Button>
        <!-- 确认按钮。宽度必须恒定：DialogFooter 是 justify-end、本按钮在
             右侧，宽度一变就会把左侧的「取消」推得位移。

             **不要用 spinner 图标**（2026-10-09 用户反馈后定案）：
               * `v-if` 渲染 → 出现/消失时宽度突变 24px（16 图标 + 8 间距），
                 点一下按钮就变宽，观感很差；
               * 改成「始终渲染 + invisible 占位」→ 平时左侧永远空一块，
                 用户明确反馈「删除按钮出现前导空位」（附了截图）；
               * 做成绝对定位 → 图标会压在文字上或溢出按钮，且要额外算坐标。
             结论：**这一层根本不需要图形 spinner**。加载态用
             「文案变化 + disabled + min-w 锁宽」表达，零占位、零位移，
             也与 AccountList 启停按钮「文案恒为启动/停止」的既有思路一致。

             min-w-[92px] 的来历：「删除中…」（3 汉字 + 1 省略号 ≈ 60px）
             比「删除」（2 汉字 ≈ 40px）宽，不锁宽就会撑开。92px 取
             「取消」(40) 与「删除中…」(60) 两者加内边距后的较大者，
             留 8px 余量 —— 实测两态宽度一致，无位移。 -->
        <Button
          :variant="confirmButtonVariant"
          :disabled="loading"
          class="min-w-[92px]"
          @click="emit('confirm')"
        >
          {{ loading ? loadingText : (confirmText ?? "确定") }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
