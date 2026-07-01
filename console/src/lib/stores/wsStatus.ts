// Console WebSocket connection status (Desktop Hardening).
//
// Fed directly from ConsoleWS's socket lifecycle (see lib/ws/console_ws.ts) so
// the header can show a real connection indicator. Deliberately NOT inferred
// from agent statuses: a WS drop calls fleetStore.markAllOffline(), so reading
// health back from agent status would be circular — the drop is what set them
// offline. The header must show "reconnecting", not a phantom fleet outage.

import { writable } from 'svelte/store';

export type WsStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed';

export const wsStatus = writable<WsStatus>('idle');
