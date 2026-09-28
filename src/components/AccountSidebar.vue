<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const props = defineProps<{
  accounts: Array<{ id: string; remark: string; running: boolean }>;
  selectedAccountId: string | null;
  loading?: boolean;
}>();

const emit = defineEmits<{
  select: [accountId: string];
  add: [];
  remove: [accountId: string];
  start: [accountId: string];
  stop: [accountId: string];
}>();

const runningCount = computed(() => props.accounts.filter((a) => a.running).length);
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- 头部 -->
    <div class="flex items-center justify-between p-4">
      <h2 class="text-sm font-semibold">账号列表</h2>
      <Button size="sm" variant="outline" class="h-7 text-xs" @click="emit('add')">
        + 添加
      </Button>
    </div>

    <Separator />

    <!-- 账号列表 -->
    <div class="flex-1 overflow-y-auto p-2">
      <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">
        加载中...
      </div>
      <div v-else-if="accounts.length === 0" class="py-8 text-center text-sm text-muted-foreground">
        暂无账号
      </div>
      <div v-else class="space-y-1">
        <button
          v-for="account in accounts"
          :key="account.id"
          class="flex w-full items-center justify-between rounded-lg p-2 text-left hover:bg-accent/50 transition-colors"
          :class="{ 'bg-accent': selectedAccountId === account.id }"
          @click="emit('select', account.id)"
        >
          <div class="flex items-center gap-2">
            <span
              class="h-2 w-2 rounded-full"
              :class="account.running ? 'bg-green-500' : 'bg-muted'"
            />
            <span class="text-sm">{{ account.remark || account.id.slice(0, 8) }}</span>
          </div>
          <div class="flex items-center gap-1">
            <Button
              v-if="!account.running"
              size="sm"
              variant="ghost"
              class="h-6 text-xs"
              @click.stop="emit('start', account.id)"
            >
              启动
            </Button>
            <Button
              v-else
              size="sm"
              variant="ghost"
              class="h-6 text-xs text-red-500"
              @click.stop="emit('stop', account.id)"
            >
              停止
            </Button>
            <Button
              size="sm"
              variant="ghost"
              class="h-6 w-6 p-0 text-muted-foreground hover:text-red-500"
              @click.stop="emit('remove', account.id)"
            >
              ✕
            </Button>
          </div>
        </button>
      </div>
    </div>

    <!-- 底部统计 -->
    <Separator />
    <div class="p-4">
      <div class="flex items-center justify-between text-sm">
        <span class="text-muted-foreground">运行中</span>
        <span class="font-medium">{{ runningCount }} / {{ accounts.length }}</span>
      </div>
    </div>
  </div>
</template>
