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
  clear: [options: { cache: boolean; logs: boolean; temp: boolean }];
}>();

const options = ref({
  cache: true,
  logs: true,
  temp: true,
});

function handleClear() {
  emit("clear", options.value);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>清理数据</DialogTitle>
        <DialogDescription>
          清理缓存、日志和临时文件
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div class="space-y-3">
          <div class="flex items-center space-x-2">
            <Checkbox id="cache" v-model:checked="options.cache" />
            <Label for="cache">缓存文件</Label>
          </div>
          <div class="flex items-center space-x-2">
            <Checkbox id="logs" v-model:checked="options.logs" />
            <Label for="logs">日志文件</Label>
          </div>
          <div class="flex items-center space-x-2">
            <Checkbox id="temp" v-model:checked="options.temp" />
            <Label for="temp">临时文件</Label>
          </div>
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button @click="handleClear">
          清理
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
