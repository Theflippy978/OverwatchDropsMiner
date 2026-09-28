<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  title: string;
  description?: string;
  showAction?: boolean;
  actionText?: string;
}>();

const emit = defineEmits<{
  action: [];
}>();
</script>

<template>
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-2xl font-bold">{{ title }}</h1>
      <p v-if="description" class="text-sm text-muted-foreground">
        {{ description }}
      </p>
    </div>
    <Button v-if="showAction" @click="emit('action')">
      {{ actionText || "操作" }}
    </Button>
  </div>
</template>
