import type { Exchange } from "./direct-chat.ts";

export type ChatPage = {
  items: Exchange[];
  next_cursor: number;
  has_more: boolean;
};

export function mergeExchanges(
  current: Exchange[],
  incoming: Exchange[],
): Exchange[] {
  const byId = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) byId.set(item.id, item);
  const next = [...byId.values()].sort((a, b) => a.sequence - b.sequence);
  return JSON.stringify(current) === JSON.stringify(next) ? current : next;
}

/** Refresh only the selected history window; expand it solely on Load more. */
export function chatPages(
  read: (query: string) => Promise<ChatPage>,
  update: (items: Exchange[], hasOlder: boolean) => void,
) {
  let oldest: number | null = null;
  let hasOlder = false;
  let pending = Promise.resolve();
  const serialize = (operation: () => Promise<void>) => {
    const result = pending.then(operation);
    pending = result.catch(() => {});
    return result;
  };
  return {
    refresh: () =>
      serialize(async () => {
        if (oldest === null) {
          const page = await read("direction=backward&limit=100");
          oldest = page.items[0]?.sequence ?? null;
          hasOlder = page.has_more;
          update(page.items, hasOlder);
          return;
        }
        const items: Exchange[] = [];
        let cursor = oldest - 1;
        let more = true;
        while (more) {
          const page = await read(`after=${cursor}&limit=100`);
          items.push(...page.items);
          if (page.has_more && page.next_cursor <= cursor)
            throw new Error("History could not advance. Please try again.");
          cursor = page.next_cursor;
          more = page.has_more;
        }
        update(items, hasOlder);
      }),
    older: (beforeUpdate: () => void) =>
      serialize(async () => {
        if (oldest === null || !hasOlder) return;
        const page = await read(
          `direction=backward&before=${oldest}&limit=100`,
        );
        // Capture the viewport after the read, so scrolling during the request is respected.
        if (page.items.length) beforeUpdate();
        oldest = page.items[0]?.sequence ?? oldest;
        hasOlder = page.has_more;
        update(page.items, hasOlder);
      }),
  };
}
