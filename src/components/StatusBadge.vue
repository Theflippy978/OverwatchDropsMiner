<script setup lang="ts">
import { computed } from "vue";
import { Badge } from "@/components/ui/badge";

const props = defineProps<{
  variant?: "default" | "secondary" | "destructive" | "outline";
  pulse?: boolean;
}>();

const badgeVariant = computed(() => props.variant || "default");
</script>

<template>
  <Badge :variant="badgeVariant" class="gap-1">
    <span
      v-if="pulse"
      class="h-2 w-2 rounded-full bg-current animate-pulse"
    />
    <slot />
  </Badge>
</template>
