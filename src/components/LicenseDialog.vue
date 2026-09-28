<script setup lang="ts">
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

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
}>();
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>许可证</DialogTitle>
        <DialogDescription>
          GPL v3 许可证
        </DialogDescription>
      </DialogHeader>
      
      <ScrollArea class="h-96">
        <div class="space-y-4 py-4 text-xs text-muted-foreground">
          <p>
            GNU GENERAL PUBLIC LICENSE
            Version 3, 29 June 2007
          </p>
          <p>
            Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
          </p>
          <p>
            Everyone is permitted to copy and distribute verbatim copies
            of this license document, but changing it is not allowed.
          </p>
          <h3 class="text-sm font-medium text-foreground">Preamble</h3>
          <p>
            The GNU General Public License is a free, copyleft license for
            software and other kinds of works.
          </p>
          <p>
            The licenses for most software and other practical works are designed
            to take away your freedom to share and change the works. By contrast,
            the GNU General Public License is intended to guarantee your freedom to
            share and change all versions of a program--to make sure it remains free
            software for all its users.
          </p>
        </div>
      </ScrollArea>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          关闭
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
