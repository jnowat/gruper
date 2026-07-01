<!-- Small colour+initials avatar for an agent, used wherever an agent appears
     (composer, round table, result header) so identity reads consistently.
     Takes id + name (not a full Agent) so it also works for round-table turns. -->
<script lang="ts">
  import { agentColor, agentInitials } from '$lib/agentDisplay.js';
  let { id, name, size = 28 }: { id: string; name: string; size?: number } = $props();
</script>

<span
  class="rounded-md inline-flex items-center justify-center font-semibold text-white flex-shrink-0 leading-none"
  style="background-color: {agentColor(id)}; width: {size}px; height: {size}px; font-size: {Math.round(size * 0.4)}px"
  title={name}
>
  {agentInitials(name)}
</span>
