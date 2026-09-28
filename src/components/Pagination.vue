<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  currentPage: number;
  totalPages: number;
  maxVisible?: number;
}>();

const emit = defineEmits<{
  "update:currentPage": [page: number];
}>();

const visiblePages = computed(() => {
  const max = props.maxVisible || 5;
  const half = Math.floor(max / 2);
  let start = Math.max(1, props.currentPage - half);
  let end = Math.min(props.totalPages, start + max - 1);
  
  if (end - start < max - 1) {
    start = Math.max(1, end - max + 1);
  }
  
  return Array.from({ length: end - start + 1 }, (_, i) => start + i);
});

function goToPage(page: number) {
  if (page >= 1 && page <= props.totalPages) {
    emit("update:currentPage", page);
  }
}
</script>

<template>
  <div class="flex items-center justify-center gap-1">
    <Button
      variant="outline"
      size="sm"
      :disabled="currentPage <= 1"
      @click="goToPage(currentPage - 1)"
    >
      上一页
    </Button>
    
    <Button
      v-for="page in visiblePages"
      :key="page"
      :variant="page === currentPage ? 'default' : 'outline'"
      size="sm"
      @click="goToPage(page)"
    >
      {{ page }}
    </Button>
    
    <Button
      variant="outline"
      size="sm"
      :disabled="currentPage >= totalPages"
      @click="goToPage(currentPage + 1)"
    >
      下一页
    </Button>
  </div>
</template>
