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
import { Progress } from "@/components/ui/progress";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  optimize: [options: { defrag: boolean; compress: boolean; index: boolean }];
}>();

const options = ref({
  defrag: true,
  compress: true,
  index: true,
});

const optimizing = ref(false);
const progress = ref(0);

function handleOptimize() {
  optimizing.value = true;
  progress.value = 0;
  
  const interval = setInterval(() => {
    progress.value += 10;
    if (progress.value >= 100) {
      clearInterval(interval);
      optimizing.value = false;
      emit("optimize", options.value);
    }
  }, 200);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>优化数据库</DialogTitle>
        <DialogDescription>
          优化数据库性能，提高查询速度
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div v-if="optimizing" class="space-y-2">
          <Progress :value="progress" class="h-2" />
          <p class="text-center text-sm text-muted-foreground">
            优化中... {{ progress }}%
          </p>
        </div>
        
        <div v-else class="space-y-3">
          <div class="flex items-center space-x-2">
            <Checkbox id="defrag" v-model:checked="options.defrag" />
            <Label for="defrag">碎片整理</Label>
          </div>
          <div class="flex items-center space-x-2">
            <Checkbox id="compress" v-model:checked="options.compress" />
            <Label for="compress">数据压缩</Label>
          </div>
          <div class="flex items-center space-x-2">
            <Checkbox id="index" v-model:checked="options.index" />
            <Label for="index">重建索引</Label>
          </div>
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button :disabled="optimizing" @click="handleOptimize">
          {{ optimizing ? "优化中..." : "开始优化" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
