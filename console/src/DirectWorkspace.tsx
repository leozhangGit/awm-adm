import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api.ts";
import { Notice } from "./components.tsx";
import { ChatHistory } from "./ChatHistory.tsx";
import { chatPages, mergeExchanges } from "./chat-pages.ts";
import type { ChatPage } from "./chat-pages.ts";
import type { Adm } from "./types.ts";
import { readDraft, saveDraft } from "./draft.ts";
import {
  resolveReference,
  newMessage,
  outcomeNote,
  replyText,
  savedMessage,
  working,
} from "./direct-chat.ts";
import type { Exchange, Message } from "./direct-chat.ts";

type Attachment = {
  id: string;
  name: string;
  byte_count: number;
  current_source_version: string | null;
};
export function DirectWorkspace({
  adm,
  channel,
}: {
  adm: Adm;
  channel: "ask" | "teach";
}) {
  const prefix = `adm-chat:${adm.id}:${channel}`;
  const [text, setText] = useState(() => readDraft(sessionStorage, prefix));
  const [items, setItems] = useState<Exchange[]>([]);
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const pages = useRef<ReturnType<typeof chatPages> | null>(null);
  const olderPending = useRef(false);
  const [connection, setConnection] = useState("loading");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState("");
  const [pending, setPending] = useState<Message | null>(() =>
    savedMessage(sessionStorage, prefix + ":pending"),
  );
  const [previous, setPrevious] = useState<string | null>(
    () => readDraft(sessionStorage, prefix + ":reply") || null,
  );
  const [files, setFiles] = useState<Attachment[]>([]);
  const [selected, setSelected] = useState<string[]>(() => {
    try {
      const v = JSON.parse(
        readDraft(sessionStorage, prefix + ":files") || "[]",
      );
      return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
    } catch {
      return [];
    }
  });
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    saveDraft(sessionStorage, prefix + ":files", JSON.stringify(selected));
  }, [prefix, selected]);
  async function upload(file: File) {
    setUploading(true);
    setError("");
    try {
      if (file.size > 262144)
        throw new Error(
          "Choose a text or Markdown file no larger than 256 KiB.",
        );
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      const existing = files.find((f) => f.name === file.name);
      const saved = await api<Attachment>(`/adms/${adm.id}/attachments`, {
        method: "POST",
        body: {
          idempotency_key: crypto.randomUUID(),
          name: file.name,
          content,
          media_type: file.name.endsWith(".md")
            ? "text/markdown"
            : "text/plain",
          ...(existing?.current_source_version
            ? { supersedes_version: existing.current_source_version }
            : {}),
        },
      });
      setFiles((old) => [...old.filter((f) => f.id !== saved.id), saved]);
      setSelected((old) => [...new Set([...old, saved.id])]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  const mounted = useRef(true);
  const clearPending = () => {
    setPending(null);
    sessionStorage.removeItem(prefix + ":pending");
  };
  useEffect(() => {
    saveDraft(sessionStorage, prefix, text);
  }, [prefix, text]);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    const history = chatPages(
      (query) =>
        api<ChatPage>(`/adms/${adm.id}/chat/${channel}?${query}`, {
          signal: controller.signal,
        }),
      (incoming, more) => {
        if (controller.signal.aborted) return;
        setItems((old) => mergeExchanges(old, incoming));
        setHasOlder(more);
        const lost = savedMessage(sessionStorage, prefix + ":pending");
        const found =
          lost &&
          incoming.find((i) => i.idempotency_key === lost.idempotency_key);
        if (found) {
          clearPending();
          setSelected([]);
          setPrevious(found.id);
          saveDraft(sessionStorage, prefix + ":reply", found.id);
          setText((current) => (current === lost.text ? "" : current));
        }
      },
    );
    pages.current = history;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const state = await api<{ state: string }>("/connection", {
          signal: controller.signal,
        });
        if (channel === "teach") {
          const attachments = await api<{ items: Attachment[] }>(
            `/adms/${adm.id}/attachments`,
            { signal: controller.signal },
          );
          if (mounted.current)
            setFiles((old) =>
              JSON.stringify(old) === JSON.stringify(attachments.items)
                ? old
                : attachments.items,
            );
        }
        await history.refresh();
        if (!mounted.current) return;
        setConnection(state.state);
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 2500);
      }
    };
    void refresh();
    return () => {
      mounted.current = false;
      controller.abort();
      if (pages.current === history) pages.current = null;
      clearTimeout(timer);
    };
  }, [adm.id, channel, prefix]);
  async function loadOlder(preserve: () => void) {
    if (olderPending.current || !pages.current) return;
    olderPending.current = true;
    setLoadingOlder(true);
    setError("");
    try {
      await pages.current.older(preserve);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      olderPending.current = false;
      if (mounted.current) setLoadingOlder(false);
    }
  }
  async function send() {
    if (sending) return;
    setSending(true);
    setError("");
    try {
      const body =
        pending ||
        newMessage(
          channel,
          text,
          selected,
          await resolveReference(items, previous, (id) =>
            api<Exchange>(`/adms/${adm.id}/interactions/${id}`),
          ),
        );
      if (!mounted.current) return;
      setPending(body);
      sessionStorage.setItem(prefix + ":pending", JSON.stringify(body));
      const result = await api<Exchange>(`/adms/${adm.id}/${channel}`, {
        method: "POST",
        body,
      });
      if (!mounted.current) return;
      clearPending();
      setSelected([]);
      setText("");
      setPrevious(result.id);
      saveDraft(sessionStorage, prefix + ":reply", result.id);
      setItems((old) => mergeExchanges(old, [result]));
    } catch (e) {
      if (!mounted.current) return;
      if (e instanceof ApiError && e.status < 500) clearPending();
      setError((e as Error).message);
    } finally {
      if (mounted.current) setSending(false);
    }
  }
  return (
    <section
      className="direct-workspace"
      aria-label={`${channel === "ask" ? "Ask" : "Teach"} ${adm.name}`}
    >
      {connection !== "enabled" && connection !== "loading" && (
        <Notice>
          Enable your connection in <a href="#view=connections">Connections</a>{" "}
          to {channel === "ask" ? "ask a question" : "teach this model"}.
        </Notice>
      )}
      {error && <Notice error>{error}</Notice>}
      <ChatHistory
        version={items}
        hasOlder={hasOlder}
        loadingOlder={loadingOlder}
        onLoadMore={loadOlder}
      >
        {!items.length && (
          <p className="empty-chat">
            {channel === "ask"
              ? "Ask about this model’s knowledge or what follows from its rules."
              : "Tell the model what you want it to learn. It will ask if something needs clarification."}
          </p>
        )}
        {items.map((item) => (
          <article
            key={item.id}
            data-exchange-id={item.id}
            className="chat-exchange"
          >
            <div className="chat-message owner">
              <small className="chat-author">
                You{item.origin === "api" ? " · API" : ""} ·{" "}
                {new Date(item.created_at_ms).toLocaleString()}
              </small>
              <p className="chat-prose">{item.text || "Supplied material"}</p>
            </div>
            <div className="chat-message system">
              <small className="chat-author">
                {adm.name}
                {working(item.status) ? " · Working" : ""}
              </small>
              <p className="chat-prose">{replyText(item)}</p>
              {working(item.status) && (
                <button
                  className="text-button"
                  disabled={Boolean(stopping)}
                  onClick={async () => {
                    setStopping(item.id);
                    try {
                      const next = await api<Exchange>(
                        `/adms/${adm.id}/interactions/${item.id}/cancel`,
                        { method: "POST" },
                      );
                      setItems((old) =>
                        old.map((row) => (row.id === item.id ? next : row)),
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setStopping("");
                    }
                  }}
                >
                  {stopping === item.id ? "Stopping…" : "Stop"}
                </button>
              )}
              {outcomeNote(item) && (
                <p className="checked-outcome">{outcomeNote(item)}</p>
              )}
            </div>
          </article>
        ))}
      </ChatHistory>
      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label htmlFor={`message-${channel}`}>
          {channel === "ask" ? "Your question" : "What should the model learn?"}
        </label>
        <textarea
          id={`message-${channel}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={16384}
          disabled={sending || Boolean(pending)}
          placeholder={
            channel === "ask" ? "Ask this model…" : "Teach this model…"
          }
        />
        {channel === "teach" && (
          <div className="chat-attachments">
            <input
              ref={fileInput}
              type="file"
              accept=".md,.txt,text/plain,text/markdown"
              aria-label="Attach text or Markdown"
              disabled={uploading || sending || Boolean(pending)}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            {uploading && <span role="status">Attaching…</span>}
            {files.length > 0 && (
              <div className="attachment-choices" aria-label="Saved files">
                {files.map((file) => (
                  <label key={file.id}>
                    <input
                      type="checkbox"
                      checked={selected.includes(file.id)}
                      disabled={sending || Boolean(pending)}
                      onChange={(e) =>
                        setSelected((old) =>
                          e.target.checked
                            ? [...old, file.id]
                            : old.filter((id) => id !== file.id),
                        )
                      }
                    />
                    {file.name} · {Math.ceil(file.byte_count / 1024)} KiB
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="chat-composer-footer">
          {pending && !sending && (
            <small>
              The submission is retained. Retry sends the same message without
              duplicating accepted work.
            </small>
          )}
          <button
            className="primary"
            disabled={
              sending ||
              uploading ||
              adm.archived ||
              connection !== "enabled" ||
              (!pending && !text.trim() && !selected.length)
            }
          >
            {sending ? "Sending…" : pending ? "Retry sending" : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}
