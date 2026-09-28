<script setup lang="ts">
import { ref } from "vue";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  submit: [feedback: string];
}>();

const feedback = ref("");

function handleSubmit() {
  if (feedback.value.trim()) {
    emit("submit", feedback.value);
    feedback.value = "";
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>意见反馈</DialogTitle>
        <DialogDescription>
          告诉我们您的使用体验和改进建议
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div class="space-y-2">
          <Label>反馈内容</Label>
          <Textarea
            v-model="feedback"
            placeholder="请输入您的反馈..."
            rows="4"
          />
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button @click="handleSubmit">
          提交
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
