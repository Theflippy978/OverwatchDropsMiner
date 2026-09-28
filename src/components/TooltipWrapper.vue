<script setup lang="ts">
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

defineProps<{
  content: string;
  side?: "top" | "right" | "bottom" | "left";
}>();
</script>

<template>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger as-child>
        <slot />
      </TooltipTrigger>
      <TooltipContent :side="side">
        <p>{{ content }}</p>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
