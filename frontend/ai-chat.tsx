/**
 * AI Chat Widget — embeddable chat floating panel component
 *
 * Adapted from pedromello.cc's components/ai-chat.tsx implementation, generalized for reuse.
 *
 * Usage:
 *   import { AiChat } from "@/components/ai-chat";
 *   // Place <AiChat /> in your layout or page
 *
 * Dependencies:
 *   - framer-motion
 *   - Tailwind CSS
 *   - React 18+
 *
 * Backend API:
 *   POST /api/chat    — streaming chat
 *   POST /api/suggest — follow-up suggestions
 *
 * The default API base URL can be configured via the AiChat apiBase prop.
 */

"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion, MotionConfig } from "framer-motion";

// ═══════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════

type Content =
  | { type: "prompt"; body: string }
  | { type: "response"; text: string; streaming?: boolean; sources?: string[] }
  | { type: "error"; body: string; retryable?: boolean };

type Activity = {
  id: string;
  createdAt: number;
  content: Content;
};

type Session = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  activities: Activity[];
};

type ChatMessage = { role: "user" | "assistant"; content: string };

// ═══════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════

let fallbackId = 0;

const uid = () => {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  fallbackId += 1;
  return "chat-" + Date.now().toString(36) + "-" + fallbackId.toString(36) + "-" + Math.random().toString(36).slice(2, 10);
};

const act = (content: Content): Activity => ({
  id: uid(),
  createdAt: Date.now(),
  content,
});

const truncate = (s: string, maxLen = 38) => {
  const t = s.trim().replace(/\s+/g, " ");
  return t.length > maxLen ? t.slice(0, maxLen) + "..." : t;
};

const DEFAULT_SUGGESTIONS = [
  "What do you work on?",
  "Tell me about your experience",
  "What's your approach to your work?",
];

const EASE_OUT_STRONG = [0.23, 1, 0.32, 1] as const;
const MAX_INPUT_LENGTH = 4_000;
const SCROLL_FOLLOW_THRESHOLD = 72;

const apiBaseUrl = (value: string) => {
  const base = value.trim().replace(/\/+$/, "");
  return base === "/api" ? "" : base.endsWith("/api") ? base.slice(0, -4) : base;
};

const boundedHistory = (messages: ChatMessage[]) => {
  const bounded = messages.slice(-40);
  return bounded[0]?.role === "assistant" ? bounded.slice(1) : bounded;
};

const sourceTitles = (value: string | null) => {
  if (!value) return [];
  try {
    const sources: unknown = JSON.parse(value);
    if (!Array.isArray(sources)) return [];
    return sources.slice(0, 3).flatMap((source) => {
      if (typeof source === "string") return [source.slice(0, 240)];
      if (!source || typeof source !== "object") return [];
      const item = source as Record<string, unknown>;
      const title = item.title ?? item.name ?? item.file;
      return typeof title === "string" && title.trim() ? [title.trim().slice(0, 240)] : [];
    });
  } catch {
    return [];
  }
};

export interface AiChatStrings {
  dialogLabel: string;
  launcherLabel: string;
  history: string;
  newChat: string;
  close: string;
  noConversations: string;
  today: string;
  yesterday: string;
  justNow: string;
  minutesShort: (count: number) => string;
  hoursShort: (count: number) => string;
  daysShort: (count: number) => string;
  keepExploring: string;
  inputLabel: string;
  inputPlaceholder: string;
  send: string;
  stop: string;
  thinking: string;
  characterCount: (count: number, maximum: number) => string;
  jumpToLatest: string;
  copy: string;
  copied: string;
  retry: string;
  sources: string;
  genericError: string;
  connectionLost: string;
  noAnswer: string;
  defaultEmptyMessage: string;
  defaultSuggestions: string[];
}

const DEFAULT_STRINGS: AiChatStrings = {
  dialogLabel: "AI chat",
  launcherLabel: "Ask me anything",
  history: "This visit",
  newChat: "New chat",
  close: "Close",
  noConversations: "No conversations in this visit.",
  today: "Today",
  yesterday: "Yesterday",
  justNow: "just now",
  minutesShort: (count) => count + "m",
  hoursShort: (count) => count + "h",
  daysShort: (count) => count + "d",
  keepExploring: "Keep exploring",
  inputLabel: "Message",
  inputPlaceholder: "Ask me anything...",
  send: "Send",
  stop: "Stop generating",
  thinking: "Thinking…",
  characterCount: (count, maximum) => count.toLocaleString() + " / " + maximum.toLocaleString(),
  jumpToLatest: "Jump to latest message",
  copy: "Copy",
  copied: "Copied",
  retry: "Retry",
  sources: "Sources",
  genericError: "Something went wrong. Try again in a moment.",
  connectionLost: "Connection lost mid-answer. Try again.",
  noAnswer: "I'd rather not get into that. Ask me about my work or experience!",
  defaultEmptyMessage: "Ask me about my work, experience, and projects.",
  defaultSuggestions: DEFAULT_SUGGESTIONS,
};

// ═══════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════

interface AiChatProps {
  /** Backend API base URL, defaults to same-origin /api */
  apiBase?: string;
  /** Floating button label text */
  label?: string;
  /** Default suggestion questions */
  suggestions?: string[];
  /** Empty state prompt text */
  emptyMessage?: string;
  /** Localizable fixed UI copy. Values omitted here use English defaults. */
  strings?: Partial<AiChatStrings>;
}

export function AiChat({
  apiBase = "",
  label,
  suggestions,
  emptyMessage,
  strings,
}: AiChatProps) {
  const text = useMemo<AiChatStrings>(
    () => ({ ...DEFAULT_STRINGS, ...(strings ?? {}) }),
    [strings],
  );
  const launcherLabel = label ?? text.launcherLabel;
  const suggestionItems = suggestions ?? text.defaultSuggestions;
  const initialMessage = emptyMessage ?? text.defaultEmptyMessage;
  const apiRoot = useMemo(() => apiBaseUrl(apiBase), [apiBase]);
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"chat" | "history">("chat");
  const [{ sessions, currentId }, setStore] = useState(() => {
    const now = Date.now();
    const current: Session = {
      id: uid(),
      title: text.newChat,
      createdAt: now,
      updatedAt: now,
      activities: [],
    };
    return { sessions: [current], currentId: current.id };
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [followUps, setFollowUps] = useState<{
    sessionId: string;
    items: string[];
  }>({ sessionId: "", items: [] });

  const abortRef = useRef<AbortController | null>(null);
  const retryRef = useRef<{ sessionId: string; history: ChatMessage[] } | null>(null);
  const characterCountId = useId();
  const turnSeq = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);
  const [nearBottom, setNearBottom] = useState(true);

  const current = sessions.find((s) => s.id === currentId) ?? sessions[0];
  const lastType =
    current.activities[current.activities.length - 1]?.content.type;
  const thinking = busy && lastType === "prompt";

  function patch(id: string, fn: (s: Session) => Session) {
    setStore((st) => ({
      ...st,
      sessions: st.sessions.map((s) => (s.id === id ? fn(s) : s)),
    }));
  }

  // Client-only mount
  useEffect(() => setMounted(true), []);
  // Cancel on unmount
  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  // Auto-resize textarea
  useLayoutEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 96) + "px";
  }, [input]);

  // Only follow streaming output while the reader is already near the bottom.
  useEffect(() => {
    if (view !== "chat" || !nearBottom) return;
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: busy ? "auto" : "smooth" });
  }, [current.activities, busy, view, followUps.items, nearBottom]);

  useEffect(() => {
    if (!open) return;
    const focusPanel = () => {
      if (view === "chat") taRef.current?.focus();
      else panelRef.current?.querySelector<HTMLElement>("button, textarea")?.focus();
    };
    const frame = window.requestAnimationFrame(focusPanel);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closePanel();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
        ) ?? [],
      ).filter((element) => element.getAttribute("aria-hidden") !== "true");
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // ═══════════════════════════════════════════
  // API calls
  // ═══════════════════════════════════════════

  async function fetchFollowUps(
    sessionId: string,
    msgs: ChatMessage[],
    myTurn: number,
  ) {
    try {
      const res = await fetch(`${apiRoot}/api/suggest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: msgs, sessionId }),
      });
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data.suggestions) && turnSeq.current === myTurn) {
        setFollowUps({ sessionId, items: data.suggestions.slice(0, 3) });
      }
    } catch {
      /* noop */
    }
  }

  async function streamReply(id: string, history: ChatMessage[]) {
    const ac = new AbortController();
    abortRef.current = ac;
    const myTurn = turnSeq.current;
    let acc = "";
    let respId: string | null = null;

    try {
      const res = await fetch(`${apiRoot}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, sessionId: id }),
        signal: ac.signal,
      });

      if (!res.ok || !res.body) {
        patch(id, (s) => ({
          ...s,
          updatedAt: Date.now(),
          activities: [
            ...s.activities,
            act({
              type: "error",
              body: text.genericError,
              retryable: true,
            }),
          ],
        }));
        return;
      }

      const sources = sourceTitles(res.headers.get("x-rag-sources"));

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });

        if (!respId) {
          const newId = uid();
          respId = newId;
          patch(id, (s) => ({
            ...s,
            updatedAt: Date.now(),
            activities: [
              ...s.activities,
              {
                id: newId,
                createdAt: Date.now(),
                content: { type: "response", text: acc, streaming: true, sources },
              },
            ],
          }));
        } else {
          const fixedId = respId;
          patch(id, (s) => ({
            ...s,
            updatedAt: Date.now(),
            activities: s.activities.map((a) =>
              a.id === fixedId
                ? {
                    ...a,
                    content: { type: "response", text: acc, streaming: true, sources },
                  }
                : a,
            ),
          }));
        }
      }
      acc += decoder.decode();
      if (!respId && acc) {
        const newId = uid();
        respId = newId;
        patch(id, (s) => ({
          ...s,
          updatedAt: Date.now(),
          activities: [
            ...s.activities,
            {
              id: newId,
              createdAt: Date.now(),
              content: { type: "response", text: acc, streaming: true, sources },
            },
          ],
        }));
      }

      // Streaming done
      if (respId) {
        const fixedId = respId;
        patch(id, (s) => ({
          ...s,
          activities: s.activities.map((a) =>
            a.id === fixedId
              ? {
                  ...a,
                  content: {
                    type: "response",
                    text: acc,
                    streaming: false,
                    sources,
                  },
                }
              : a,
          ),
        }));
        fetchFollowUps(
          id,
          [...history, { role: "assistant", content: acc }],
          myTurn,
        );
      } else {
        patch(id, (s) => ({
          ...s,
          updatedAt: Date.now(),
          activities: [
            ...s.activities,
            act({
              type: "response",
              text: text.noAnswer,
            }),
          ],
        }));
      }
    } catch (err: unknown) {
      if (respId) {
        const fixedId = respId;
        patch(id, (s) => ({
          ...s,
          activities: s.activities.map((a) =>
            a.id === fixedId && a.content.type === "response"
              ? { ...a, content: { ...a.content, streaming: false } }
              : a,
          ),
        }));
      }
      if (
        ac.signal.aborted ||
        (err instanceof Error && err.name === "AbortError")
      )
        return;
      patch(id, (s) => ({
        ...s,
        updatedAt: Date.now(),
        activities: [
          ...s.activities,
            act({
              type: "error",
              body: text.connectionLost,
              retryable: true,
          }),
        ],
      }));
    } finally {
      if (abortRef.current === ac) {
        abortRef.current = null;
        setBusy(false);
      }
    }
  }

  function send(raw = input) {
    const body = raw.trim().slice(0, MAX_INPUT_LENGTH);
    if (!body || busy) return;
    setInput("");
    setView("chat");
    setNearBottom(true);
    turnSeq.current += 1;
    setFollowUps({ sessionId: "", items: [] });
    const id = currentId;

    const sessionNow = sessions.find((s) => s.id === id) ?? current;
    const history: ChatMessage[] = sessionNow.activities.flatMap((a) => {
      if (a.content.type === "prompt")
        return [{ role: "user" as const, content: a.content.body }];
      if (a.content.type === "response")
        return [{ role: "assistant" as const, content: a.content.text }];
      return [];
    });
    const bounded = boundedHistory([...history, { role: "user", content: body }]);

    patch(id, (s) => ({
      ...s,
      title: s.activities.length === 0 ? truncate(body) : s.title,
      updatedAt: Date.now(),
      activities: [...s.activities, act({ type: "prompt", body })],
    }));
    retryRef.current = { sessionId: id, history: bounded };
    setBusy(true);
    streamReply(id, bounded);
  }

  function newChat() {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    turnSeq.current += 1;
    retryRef.current = null;
    setFollowUps({ sessionId: "", items: [] });
    const now = Date.now();
    const s: Session = {
      id: uid(),
      title: text.newChat,
      createdAt: now,
      updatedAt: now,
      activities: [],
    };
    setStore((st) => ({ sessions: [s, ...st.sessions], currentId: s.id }));
    setView("chat");
    setNearBottom(true);
    setTimeout(() => taRef.current?.focus(), 0);
  }

  function isAtBottom() {
    const el = scrollRef.current;
    return !el || el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_FOLLOW_THRESHOLD;
  }

  function scrollToLatest() {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setNearBottom(true);
  }

  function closePanel() {
    stopGenerating();
    setOpen(false);
    window.requestAnimationFrame(() => {
      (lastFocusedRef.current ?? triggerRef.current)?.focus();
    });
  }

  function stopGenerating() {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  }

  function retryLastRequest() {
    const last = retryRef.current;
    if (!last || busy) return;
    turnSeq.current += 1;
    setView("chat");
    setNearBottom(true);
    setBusy(true);
    streamReply(last.sessionId, last.history);
  }

  function openPanel() {
    lastFocusedRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : triggerRef.current;
    setOpen(true);
  }

  // ═══════════════════════════════════════════
  // History grouping
  // ═══════════════════════════════════════════

  const grouped = useMemo(() => {
    const active = sessions.filter((s) => s.activities.length > 0);
    const sorted = [...active].sort(
      (a, b) => b.updatedAt - a.updatedAt,
    );
    const startOfDay = (t: number) => {
      const d = new Date(t);
      d.setHours(0, 0, 0, 0);
      return d.getTime();
    };
    const today = startOfDay(Date.now());
    const DAY = 86_400_000;
    const groups: Record<string, Session[]> = {};
    for (const s of sorted) {
      const diff = Math.round((today - startOfDay(s.updatedAt)) / DAY);
      const label =
        diff <= 0
          ? text.today
          : diff === 1
            ? text.yesterday
            : new Date(s.updatedAt).toLocaleDateString();
      (groups[label] ??= []).push(s);
    }
    return groups;
  }, [sessions, text.today, text.yesterday]);

  // ═══════════════════════════════════════════
  // Render
  // ═══════════════════════════════════════════

  if (!mounted) return null;

  return (
    <MotionConfig reducedMotion="user">
      <div className="fixed bottom-5 right-5 z-50 font-sans">
        {/* FAB Button */}
        <AnimatePresence initial={false}>
          {!open && (
            <motion.button
              key="fab"
              initial={{ opacity: 0, scale: 0.9, y: 4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 4 }}
              transition={{ type: "spring", stiffness: 460, damping: 30 }}
              ref={triggerRef}
              onClick={openPanel}
              aria-haspopup="dialog"
              aria-expanded={open}
              className="absolute bottom-0 right-0 inline-flex h-11 w-max items-center gap-2 whitespace-nowrap rounded-[10px] bg-white px-3.5 text-[13px] font-medium text-neutral-900 shadow-lg ring-1 ring-neutral-200 transition-[background-color,scale] hover:bg-neutral-50 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:bg-neutral-900 dark:text-neutral-100 dark:ring-neutral-700 dark:hover:bg-neutral-800"
            >
              <ChatIcon className="h-4 w-4" />
              {launcherLabel}
            </motion.button>
          )}
        </AnimatePresence>

        {/* Chat Panel */}
        <AnimatePresence>
          {open && (
            <motion.section
              key="panel"
              role="dialog"
              aria-modal="true"
              aria-label={text.dialogLabel}
              ref={panelRef}
              initial={{ opacity: 0, scale: 0.96, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{
                opacity: 0,
                scale: 0.97,
                y: 8,
                transition: { duration: 0.16, ease: EASE_OUT_STRONG },
              }}
              transition={{ duration: 0.32, ease: EASE_OUT_STRONG }}
              style={{ transformOrigin: "bottom right" }}
              className="fixed inset-x-0 bottom-0 flex h-[85dvh] w-full flex-col overflow-hidden rounded-t-2xl bg-white/95 shadow-2xl backdrop-blur-xl ring-1 ring-neutral-200 sm:absolute sm:inset-x-auto sm:bottom-0 sm:right-0 sm:h-[32rem] sm:max-h-[80vh] sm:w-[24rem] sm:max-w-[calc(100vw_-_2.5rem)] sm:rounded-2xl dark:bg-neutral-950/95 dark:ring-neutral-800"
            >
              {/* Header */}
              <header className="flex h-14 shrink-0 items-center gap-1 border-b border-neutral-200 pl-3.5 pr-1 dark:border-neutral-800">
                <span className="flex-1 truncate text-[13px] font-medium text-neutral-900 dark:text-neutral-100">
                  {view === "history" ? text.history : current.title}
                </span>
                <IconButton
                  label={text.history}
                  active={view === "history"}
                  onClick={() =>
                    setView((v) => (v === "history" ? "chat" : "history"))
                  }
                >
                  <ClockIcon />
                </IconButton>
                <IconButton label={text.newChat} onClick={newChat}>
                  <PlusIcon />
                </IconButton>
                <IconButton label={text.close} onClick={closePanel}>
                  <CloseIcon />
                </IconButton>
              </header>

              {/* History View */}
              {view === "history" ? (
                <div className="flex-1 overflow-y-auto px-1.5 py-2">
                  {Object.keys(grouped).length === 0 ? (
                    <p className="px-2.5 py-6 text-center text-[13px] text-neutral-500">
                      {text.noConversations}
                    </p>
                  ) : (
                    Object.entries(grouped).map(([label, items]) => (
                      <div key={label} className="mb-1.5">
                        <h4 className="px-2.5 py-1 text-[11px] font-semibold text-neutral-400">
                          {label}
                        </h4>
                        {items.map((s) => (
                          <button
                            key={s.id}
                            onClick={() => {
                              setStore((st) => ({
                                ...st,
                                currentId: s.id,
                              }));
                              setFollowUps({ sessionId: "", items: [] });
                              setView("chat");
                              setNearBottom(true);
                            }}
                            className="flex min-h-11 w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-800"
                          >
                            <span className="flex-1 truncate text-[13px] text-neutral-900 dark:text-neutral-100">
                              {s.title}
                            </span>
                            <span className="shrink-0 text-[12px] tabular-nums text-neutral-400">
                              {relativeTime(s.updatedAt, text)}
                            </span>
                          </button>
                        ))}
                      </div>
                    ))
                  )}
                </div>
              ) : (
                /* Chat View */
                <div className="relative flex min-h-0 flex-1">
                <div
                  ref={scrollRef}
                  role="log"
                  aria-label={text.dialogLabel}
                  aria-live="polite"
                  aria-relevant="additions text"
                  onScroll={() => setNearBottom(isAtBottom())}
                  className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-3.5 py-3.5"
                >
                  {current.activities.length === 0 && !busy ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
                      <ChatIcon className="h-10 w-10 text-neutral-300 dark:text-neutral-700" />
                      <p className="max-w-[15rem] text-pretty text-[13px] leading-relaxed text-neutral-500">
                        {initialMessage}
                      </p>
                      <div className="flex flex-wrap items-center justify-center gap-1.5">
                        {suggestionItems.map((q) => (
                          <button
                            key={q}
                            onClick={() => send(q)}
                            className="min-h-11 rounded-full border border-neutral-200 px-3 py-1.5 text-[12px] text-neutral-700 transition-colors hover:bg-neutral-100 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <>
                      {current.activities.map((a) => (
                        <ActivityRow key={a.id} content={a.content} strings={text} onRetry={retryLastRequest} />
                      ))}
                      {thinking && <ThinkingRow label={text.thinking} />}
                      {!busy &&
                        lastType === "response" &&
                        followUps.sessionId === current.id &&
                        followUps.items.length > 0 && (
                          <FollowUps
                            items={followUps.items}
                            onPick={(q) => send(q)}
                            label={text.keepExploring}
                          />
                        )}
                    </>
                  )}
                </div>
                {!nearBottom && current.activities.length > 0 && (
                  <button
                    type="button"
                    onClick={scrollToLatest}
                    className="absolute bottom-3 left-1/2 min-h-11 -translate-x-1/2 rounded-full bg-neutral-900 px-4 text-[12px] font-medium text-white shadow-lg transition-colors hover:bg-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:bg-white dark:text-neutral-900"
                  >
                    {text.jumpToLatest}
                  </button>
                )}
                </div>
              )}

              {/* Input Area */}
              {view === "chat" && (
                <div className="shrink-0 px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:pb-3">
                  <div className="rounded-[11px] border border-neutral-200 bg-neutral-50 px-3 py-2.5 transition-colors focus-within:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 dark:focus-within:border-neutral-600">
                    <textarea
                      ref={taRef}
                      rows={1}
                      value={input}
                      aria-label={text.inputLabel}
                      aria-describedby={characterCountId}
                      aria-busy={busy}
                      maxLength={MAX_INPUT_LENGTH}
                      placeholder={text.inputPlaceholder}
                      onChange={(e) => setInput(e.target.value.slice(0, MAX_INPUT_LENGTH))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                          e.preventDefault();
                          send();
                        }
                      }}
                      className="max-h-24 w-full resize-none bg-transparent text-[13px] leading-relaxed text-neutral-900 outline-none placeholder:text-neutral-400 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                    />
                    <div className="mt-1.5 flex items-center gap-2">
                      <span id={characterCountId} className="flex-1 text-[11px] tabular-nums text-neutral-400">
                        {busy ? text.thinking + " - " : ""}{text.characterCount(input.length, MAX_INPUT_LENGTH)}
                      </span>
                      <button
                        onClick={() => (busy ? stopGenerating() : send())}
                        disabled={!busy && !input.trim()}
                        aria-label={busy ? text.stop : text.send}
                        className={`grid h-11 w-11 place-items-center rounded-full transition-[background-color,color,scale] active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 ${
                          busy || input.trim()
                            ? "bg-neutral-900 text-white hover:opacity-90 dark:bg-white dark:text-neutral-900"
                            : "bg-neutral-100 text-neutral-400 dark:bg-neutral-700"
                        }`}
                      >
                        {busy ? <CloseIcon /> : <ArrowUpIcon />}
                      </button>
                    </div>
                  </div>
                </div>
              )}
              <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
                {busy ? text.thinking : ""}
              </p>
            </motion.section>
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}

// ═══════════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════════

function ActivityRow({
  content,
  strings,
  onRetry,
}: {
  content: Content;
  strings: AiChatStrings;
  onRetry: () => void;
}) {
  if (content.type === "prompt") {
    return (
      <motion.div
        layout
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 420, damping: 32 }}
        className="flex justify-end"
      >
        <div className="max-w-[85%] rounded-[12px] bg-neutral-100 px-3 py-2 text-[13px] leading-relaxed text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100">
          {content.body}
        </div>
      </motion.div>
    );
  }

  if (content.type === "error") {
    return (
      <div role="alert" className="flex items-center gap-2 text-[13px] leading-relaxed text-red-500">
        {content.body}
        {content.retryable && (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-md px-2 text-[12px] font-medium text-red-700 underline decoration-red-300 underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:text-red-300"
          >
            {strings.retry}
          </button>
        )}
      </div>
    );
  }

  // Response — no layout prop to avoid height bounce during streaming
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 420, damping: 32 }}
      className="group/resp text-[13px] leading-relaxed text-neutral-700 dark:text-neutral-300"
    >
      <div>
        <span className="whitespace-pre-wrap">{content.text}</span>
        {content.streaming && (
          <motion.span
            animate={{ opacity: [1, 1, 0, 0] }}
            transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
            className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] rounded-full bg-neutral-900 align-middle dark:bg-neutral-100"
          />
        )}
      </div>

      {!content.streaming && content.text.length > 0 && (
        <div className="mt-1.5 flex items-center gap-1">
          <CopyButton text={content.text} strings={strings} />
        </div>
      )}
      {!content.streaming && content.sources && content.sources.length > 0 && (
        <div className="mt-2 border-l-2 border-neutral-200 pl-2 text-[12px] text-neutral-500 dark:border-neutral-700 dark:text-neutral-400">
          <span className="font-medium">{strings.sources}: </span>
          {content.sources.join(" · ")}
        </div>
      )}
    </motion.div>
  );
}

function ThinkingRow({ label }: { label: string }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ type: "spring", stiffness: 420, damping: 32 }}
      className="flex items-center gap-1.5"
      role="status"
      aria-label={label}
    >
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-neutral-400"
          animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
          transition={{
            duration: 1,
            repeat: Infinity,
            ease: "easeInOut",
            delay: i * 0.15,
          }}
        />
      ))}
    </motion.div>
  );
}

function FollowUps({
  items,
  onPick,
  label,
}: {
  items: string[];
  onPick: (q: string) => void;
  label: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
      className="mt-0.5 flex flex-col gap-0.5 border-t border-neutral-200 pt-2.5 dark:border-neutral-800"
    >
      <span className="mb-0.5 px-2 text-[11px] font-medium text-neutral-400">
        {label}
      </span>
      {items.map((q, i) => (
        <motion.button
          key={q}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            delay: i * 0.05,
            type: "spring",
            stiffness: 460,
            damping: 34,
          }}
          onClick={() => onPick(q)}
          className="group/fu flex min-h-11 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] text-neutral-700 transition-colors hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          <span className="flex-1">{q}</span>
          <ArrowUpRightIcon className="h-3.5 w-3.5 shrink-0 text-neutral-400 transition-colors group-hover/fu:text-neutral-700 dark:group-hover/fu:text-neutral-300" />
        </motion.button>
      ))}
    </motion.div>
  );
}

function CopyButton({ text, strings }: { text: string; strings: AiChatStrings }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard can be blocked */
        }
      }}
      aria-label={copied ? strings.copied : strings.copy}
      className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-[11.5px] text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
    >
      <AnimatePresence mode="wait" initial={false}>
        {copied ? (
          <motion.span
            key="ok"
            initial={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
            animate={{ scale: 1, opacity: 1, filter: "blur(0px)" }}
            exit={{ scale: 0.25, opacity: 0 }}
            transition={{ type: "spring", duration: 0.3, bounce: 0 }}
          >
            <CheckIcon className="h-3 w-3" />
          </motion.span>
        ) : (
          <motion.span
            key="copy"
            initial={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
            animate={{ scale: 1, opacity: 1, filter: "blur(0px)" }}
            exit={{ scale: 0.25, opacity: 0 }}
            transition={{ type: "spring", duration: 0.3, bounce: 0 }}
          >
            <CopyIcon className="h-3 w-3" />
          </motion.span>
        )}
      </AnimatePresence>
      {copied ? strings.copied : strings.copy}
    </button>
  );
}

function IconButton({
  children,
  label,
  active,
  onClick,
}: {
  children: ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`grid h-11 w-11 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 ${
        active
          ? "bg-neutral-100 text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100"
          : "text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
      }`}
    >
      {children}
    </button>
  );
}

// ═══════════════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════════════

function relativeTime(t: number, strings: AiChatStrings): string {
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return strings.justNow;
  if (s < 3600) return strings.minutesShort(Math.floor(s / 60));
  if (s < 86_400) return strings.hoursShort(Math.floor(s / 3600));
  return strings.daysShort(Math.floor(s / 86_400));
}

// ═══════════════════════════════════════════════════════
// SVG Icons
// ═══════════════════════════════════════════════════════

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function ChatIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" {...stroke} className={className}>
      <path d="M2.5 4.5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-4l-3 2.5v-2.5h-.5a2 2 0 0 1-1.5-3" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 16 16" {...stroke} className="h-4 w-4">
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.4 1.4" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      {...stroke}
      strokeWidth={1.6}
      className="h-4 w-4"
    >
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      {...stroke}
      strokeWidth={1.6}
      className="h-4 w-4"
    >
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

function ArrowUpIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      {...stroke}
      strokeWidth={1.7}
      className="h-4 w-4"
    >
      <path d="M8 13V3M4 6.5 8 3l4 3.5" />
    </svg>
  );
}

function ArrowUpRightIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" {...stroke} strokeWidth={1.6} className={className}>
      <path d="M5 11l6-6M6 5h5v5" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" {...stroke} strokeWidth={2} className={className}>
      <path d="M3.5 8.5 6.5 11.5 12.5 5" />
    </svg>
  );
}

function CopyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" {...stroke} className={className}>
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 5.5V4a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5" />
    </svg>
  );
}
