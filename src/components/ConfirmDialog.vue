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
</script>

<template>
  <Dialog v-model:open="isOpen">
    <!-- loading 期间禁掉 ESC / 遮罩 / X 三条关闭路径：
         删除账号是「stop_miner + remove_account」多步长耗时操作，
         中途关掉对话框会让用户失去「我再想想」的机会，
         而操作仍会跑完并真的删掉账号。按键已 disabled 却能关窗属自相矛盾。 -->
    <DialogContent
      class="sm:max-w-md"
      :close-on-escape-key-down="!loading"
      :close-on-click-outside="!loading"
      :show-close="!loading"
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
        <Button
          :variant="confirmButtonVariant"
          :disabled="loading"
          @click="emit('confirm')"
        >
          <span v-if="loading" class="mr-2 h-4 w-4 animate-spin" aria-hidden="true">⟳</span>
          {{ confirmText ?? "确定" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
