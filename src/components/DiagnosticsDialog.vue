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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
}>();

const diagnosing = ref(false);
const progress = ref(0);
const results = ref<Array<{ name: string; status: "pass" | "fail" | "warning"; message: string }>>([]);

function runDiagnostics() {
  diagnosing.value = true;
  progress.value = 0;
  results.value = [];
  
  const checks = [
    { name: "网络连接", status: "pass" as const, message: "网络连接正常" },
    { name: "数据库", status: "pass" as const, message: "数据库运行正常" },
    { name: "配置文件", status: "pass" as const, message: "配置文件完整" },
    { name: "账号状态", status: "warning" as const, message: "部分账号需要重新登录" },
    { name: "系统资源", status: "pass" as const, message: "系统资源充足" },
  ];
  
  let i = 0;
  const interval = setInterval(() => {
    if (i < checks.length) {
      results.value.push(checks[i]);
      progress.value = ((i + 1) / checks.length) * 100;
      i++;
    } else {
      clearInterval(interval);
      diagnosing.value = false;
    }
  }, 500);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>系统诊断</DialogTitle>
        <DialogDescription>
          检查系统状态和配置
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div v-if="diagnosing" class="space-y-2">
          <Progress :value="progress" class="h-2" />
          <p class="text-center text-sm text-muted-foreground">
            诊断中... {{ Math.round(progress) }}%
          </p>
        </div>
        
        <ScrollArea v-else-if="results.length > 0" class="h-64">
          <div class="space-y-2">
            <div
              v-for="result in results"
              :key="result.name"
              class="flex items-center justify-between rounded-lg border border-border p-2"
            >
              <div class="flex items-center gap-2">
                <span
                  class="h-2 w-2 rounded-full"
                  :class="{
                    'bg-green-500': result.status === 'pass',
                    'bg-red-500': result.status === 'fail',
                    'bg-yellow-500': result.status === 'warning',
                  }"
                />
                <span class="text-sm">{{ result.name }}</span>
              </div>
              <span class="text-xs text-muted-foreground">{{ result.message }}</span>
            </div>
          </div>
        </ScrollArea>
        
        <div v-else class="py-8 text-center text-sm text-muted-foreground">
          点击"开始诊断"检查系统状态
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          关闭
        </Button>
        <Button :disabled="diagnosing" @click="runDiagnostics">
          {{ diagnosing ? "诊断中..." : "开始诊断" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
