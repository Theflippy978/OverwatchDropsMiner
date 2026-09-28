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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  backup: [options: { encrypt: boolean; password?: string }];
}>();

const options = ref({
  encrypt: false,
  password: "",
  confirmPassword: "",
});

function handleBackup() {
  emit("backup", {
    encrypt: options.value.encrypt,
    password: options.value.encrypt ? options.value.password : undefined,
  });
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>备份数据</DialogTitle>
        <DialogDescription>
          创建数据备份，可选择加密保护
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div class="flex items-center space-x-2">
          <Checkbox id="encrypt" v-model:checked="options.encrypt" />
          <Label for="encrypt">加密备份</Label>
        </div>
        
        <div v-if="options.encrypt" class="space-y-4">
          <div class="space-y-2">
            <Label for="password">密码</Label>
            <Input
              id="password"
              v-model="options.password"
              type="password"
              placeholder="输入密码"
            />
          </div>
          <div class="space-y-2">
            <Label for="confirm-password">确认密码</Label>
            <Input
              id="confirm-password"
              v-model="options.confirmPassword"
              type="password"
              placeholder="再次输入密码"
            />
          </div>
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button
          :disabled="options.encrypt && (!options.password || options.password !== options.confirmPassword)"
          @click="handleBackup"
        >
          创建备份
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
