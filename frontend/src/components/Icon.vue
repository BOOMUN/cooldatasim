<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string[]> = {
  inbox: ['M4 4h16v13H8l-4 4V4Z', 'M8 8h8M8 12h5'],
  users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2', 'M13 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87', 'M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0'],
  book: ['M12 5C8 2 4 3 2 4v16c3-2 7-2 10 0 3-2 7-2 10 0V4c-3-1-7-2-10 1Z', 'M12 5v15'],
  phone: ['M21 11.5a9 9 0 0 1-13.5 7.8L3 21l1.7-4.5A9 9 0 1 1 21 11.5Z', 'M8 7c0 5 4 9 8 9l1-3-3-1-1 1-3-3 1-1-1-3-2 1Z'],
  tag: ['M20 12l-8 8-9-9V3h8l9 9Z', 'M7 7h.01'],
  sparkles: ['m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3Z', 'm20 2 1 3 2 1'],
  settings: ['m9 3-1 3-3 1-2 4 2 2-1 3 3 3 3-1 2 3 4-1 1-3 3-1 1-4-3-2V5l-4-2-2 2-3-2Z', 'M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0'],
  search: ['M21 21l-5-5', 'M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
  plus: ['M12 5v14M5 12h14'],
  arrow: ['M5 12h14m-5-5 5 5-5 5'],
  send: ['m22 2-7 20-4-9L2 9l20-7ZM22 2 11 13'],
  check: ['m5 12 4 4L19 6'],
  doublecheck: ['m2 12 4 4L16 6m-6 8 2 2L22 6'],
  close: ['m6 6 12 12M6 18 18 6'],
  refresh: ['M20 7A9 9 0 1 0 21 14', 'M20 2v5h-5'],
  external: ['M14 3h7v7m0-7-11 11', 'M10 3H3v18h18v-7'],
  edit: ['m15 5 4 4M3 21l5-1L21 7l-4-4L4 16l-1 5Z'],
  pin: ['M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z', 'M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0'],
  logout: ['M9 3H3v18h6m6-15 6 6-6 6M8 12h13'],
  shield: ['M12 2 3 6v7c0 5 9 9 9 9s9-4 9-9V6l-9-4Z', 'm8 12 3 3 5-6'],
  clock: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0', 'M12 6v6l4 2'],
  globe: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0', 'M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18'],
  file: ['M14 2H4v20h16V8l-6-6Zm0 0v6h6M8 13h8M8 17h6'],
  chevron: ['m9 5 7 7-7 7'],
  info: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0', 'M12 11v6M12 7h.01'],
  lock: ['M5 10h14v11H5V10Zm3 0V6a4 4 0 0 1 8 0v4M12 14v3'],
  menu: ['M3 6h18M3 12h18M3 18h18'],
  note: ['M3 3h18v13l-5 5H3V3Zm13 18v-5h5M7 8h10M7 12h6'],
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path v-for="(path, index) in (paths[name] || paths.file)" :key="index" :d="path" /></svg></template>
