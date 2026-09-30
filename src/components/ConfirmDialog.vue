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

const confirmButtonVariant = computed(() => props.variant || "default");
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription>{{ message }}</DialogDescription>
      </DialogHeader>
      
      <DialogFooter>
        <Button
          v-if="showCancel !== false"
          variant="outline"
          :disabled="loading"
          @click="emit('cancel')"
        >
          {{ cancelText || "取消" }}
        </Button>
        <Button
          :variant="confirmButtonVariant"
          :disabled="loading"
          @click="emit('confirm')"
        >
          <span v-if="loading" class="mr-2 h-4 w-4 animate-spin">⟳</span>
          {{ confirmText || "确定" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
