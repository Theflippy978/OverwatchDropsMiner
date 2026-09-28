<script setup lang="ts">
import { ref } from "vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const emit = defineEmits<{
  search: [query: string];
  notifications: [];
  profile: [];
}>();

const searchQuery = ref("");
</script>

<template>
  <header class="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
    <div class="flex h-14 items-center justify-between px-4">
      <!-- 左侧 -->
      <div class="flex items-center gap-4">
        <h1 class="text-lg font-bold">OW Miner</h1>
        <div class="relative">
          <svg
            class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <Input
            v-model="searchQuery"
            placeholder="搜索..."
            class="w-64 pl-9"
            @input="emit('search', searchQuery)"
          />
        </div>
      </div>

      <!-- 右侧 -->
      <div class="flex items-center gap-2">
        <Button variant="ghost" size="sm" class="relative">
          <span class="text-lg">🔔</span>
          <span class="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-red-500" />
        </Button>
        <Button variant="ghost" size="sm" @click="emit('profile')">
          <span class="text-lg">👤</span>
        </Button>
      </div>
    </div>
  </header>
</template>
