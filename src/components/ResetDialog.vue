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
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  reset: [options: { accounts: boolean; config: boolean; logs: boolean }];
}>();

const options = ref({
  accounts: false,
  config: false,
  logs: false,
});

function handleReset() {
  emit("reset", options.value);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>重置数据</DialogTitle>
        <DialogDescription>
          选择要重置的数据类型，此操作不可恢复
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div class="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
          <p class="text-sm text-red-500">
            警告：重置操作不可恢复，请谨慎操作！
          </p>
        </div>
        
        <div class="space-y-3">
          <div class="flex items-center space-x-2">
            <Checkbox id="accounts" v-model:checked="options.accounts" />
            <Label for="accounts">账号数据</Label>
          </div>
          <div class="flex items-center space-x-2">
            <Checkbox id="config" v-model:checked="options.config" />
            <Label for="config">配置文件</Label>
          </div>
          <div class="flex items-center space-x-2">
            <Checkbox id="logs" v-model:checked="options.logs" />
            <Label for="logs">日志文件</Label>
          </div>
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button
          variant="destructive"
          :disabled="!options.accounts && !options.config && !options.logs"
          @click="handleReset"
        >
          重置
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
