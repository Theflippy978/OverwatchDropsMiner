<script setup lang="ts">
import { ref } from "vue";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

defineProps<{
  darkMode: boolean;
  runningCount: number;
}>();

const emit = defineEmits<{
  toggleTheme: [];
  addAccount: [];
}>();
</script>

<template>
  <header class="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
    <div class="container mx-auto flex h-14 items-center justify-between px-4">
      <h1 class="text-lg font-bold">守望先锋直播掉宝助手</h1>
      <div class="flex items-center gap-3">
        <span class="text-sm text-muted-foreground">
          {{ runningCount }} 个账号运行中
        </span>
        <Button
          size="sm"
          variant="outline"
          @click="emit('addAccount')"
        >
          + 添加账号
        </Button>
        <button
          class="rounded-md p-2 hover:bg-accent transition-colors"
          @click="emit('toggleTheme')"
        >
          {{ darkMode ? "☀️" : "🌙" }}
        </button>
      </div>
    </div>
  </header>
</template>
