/**
 * AI Chat Widget — 可嵌入的聊天浮窗组件
 *
 * 参考 pedromello.cc 的 components/ai-chat.tsx 实现，适配为通用版本。
 *
 * 使用方式:
 *   import { AiChat } from "@/components/ai-chat";
 *   // 在 layout 或 page 中放置 <AiChat />
 *
 * 依赖:
 *   - framer-motion
 *   - Tailwind CSS
 *   - React 18+
 *
 * 后端 API:
 *   POST /api/chat    — 流式聊天
 *   POST /api/suggest — 追问建议
 *
 * 默认 API 地址可通过 AiChat 的 apiBase prop 配置。
 */

"use client";

import {
  useEffect,
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
  | { type: "response"; text: string; streaming?: boolean }
  | { type: "error"; body: string };

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

const uid = () => Math.random().toString(36).slice(2);

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

// ═══════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════

interface AiChatProps {
  /** 后端 API 地址，默认同源 /api */
  apiBase?: string;
  /** 浮动按钮显示文案 */
  label?: string;
  /** 默认建议问题 */
  suggestions?: string[];
  /** 空状态提示文案 */
  emptyMessage?: string;
}

export function AiChat({
  apiBase = "",
  label = "Ask me anything",
  suggestions = DEFAULT_SUGGESTIONS,
  emptyMessage = "Ask me about my work, experience, and projects.",
}: AiChatProps) {
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"chat" | "history">("chat");
  const [{ sessions, currentId }, setStore] = useState(() => {
    const now = Date.now();
    const current: Session = {
      id: uid(),
      title: "New chat",
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
  const turnSeq = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

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
  useEffect(() => () => abortRef.current?.abort(), []);

  // Auto-resize textarea
  useLayoutEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 96) + "px";
  }, [input]);

  // Auto-scroll
  useEffect(() => {
    if (view !== "chat") return;
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [current.activities, busy, view, followUps.items]);

  // ═══════════════════════════════════════════
  // API calls
  // ═══════════════════════════════════════════

  async function fetchFollowUps(
    sessionId: string,
    msgs: ChatMessage[],
    myTurn: number,
  ) {
    try {
      const res = await fetch(`${apiBase}/api/suggest`, {
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
      const res = await fetch(`${apiBase}/api/chat`, {
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
              body: "Something went wrong. Try again in a moment.",
            }),
          ],
        }));
        return;
      }

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
                content: { type: "response", text: acc, streaming: true },
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
                    content: { type: "response", text: acc, streaming: true },
                  }
                : a,
            ),
          }));
        }
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
              text: "I'd rather not get into that. Ask me about my work or experience!",
            }),
          ],
        }));
      }
    } catch (err: unknown) {
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
            body: "Connection lost mid-answer. Try again.",
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
    const body = raw.trim();
    if (!body || busy) return;
    setInput("");
    setView("chat");
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
    history.push({ role: "user", content: body });

    patch(id, (s) => ({
      ...s,
      title: s.activities.length === 0 ? truncate(body) : s.title,
      updatedAt: Date.now(),
      activities: [...s.activities, act({ type: "prompt", body })],
    }));
    setBusy(true);
    streamReply(id, history);
  }

  function newChat() {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    turnSeq.current += 1;
    setFollowUps({ sessionId: "", items: [] });
    const now = Date.now();
    const s: Session = {
      id: uid(),
      title: "New chat",
      createdAt: now,
      updatedAt: now,
      activities: [],
    };
    setStore((st) => ({ sessions: [s, ...st.sessions], currentId: s.id }));
    setView("chat");
    setTimeout(() => taRef.current?.focus(), 0);
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
          ? "Today"
          : diff === 1
            ? "Yesterday"
            : new Date(s.updatedAt).toLocaleDateString();
      (groups[label] ??= []).push(s);
    }
    return groups;
  }, [sessions]);

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
              onClick={() => setOpen(true)}
              className="absolute bottom-0 right-0 inline-flex h-9 w-max items-center gap-2 whitespace-nowrap rounded-[10px] bg-white px-3.5 text-[13px] font-medium text-neutral-900 shadow-lg ring-1 ring-neutral-200 transition-[background-color,scale] hover:bg-neutral-50 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:bg-neutral-900 dark:text-neutral-100 dark:ring-neutral-700 dark:hover:bg-neutral-800"
            >
              <ChatIcon className="h-4 w-4" />
              {label}
            </motion.button>
          )}
        </AnimatePresence>

        {/* Chat Panel */}
        <AnimatePresence>
          {open && (
            <motion.section
              key="panel"
              role="dialog"
              aria-label="AI Chat"
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
              <header className="flex h-11 shrink-0 items-center gap-1 border-b border-neutral-200 pl-3.5 pr-2 dark:border-neutral-800">
                <span className="flex-1 truncate text-[13px] font-medium text-neutral-900 dark:text-neutral-100">
                  {view === "history" ? "History" : current.title}
                </span>
                <IconButton
                  label="History"
                  active={view === "history"}
                  onClick={() =>
                    setView((v) => (v === "history" ? "chat" : "history"))
                  }
                >
                  <ClockIcon />
                </IconButton>
                <IconButton label="New chat" onClick={newChat}>
                  <PlusIcon />
                </IconButton>
                <IconButton label="Close" onClick={() => setOpen(false)}>
                  <CloseIcon />
                </IconButton>
              </header>

              {/* History View */}
              {view === "history" ? (
                <div className="flex-1 overflow-y-auto px-1.5 py-2">
                  {Object.keys(grouped).length === 0 ? (
                    <p className="px-2.5 py-6 text-center text-[13px] text-neutral-500">
                      No conversations yet.
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
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-800"
                          >
                            <span className="flex-1 truncate text-[13px] text-neutral-900 dark:text-neutral-100">
                              {s.title}
                            </span>
                            <span className="shrink-0 text-[12px] tabular-nums text-neutral-400">
                              {relativeTime(s.updatedAt)}
                            </span>
                          </button>
                        ))}
                      </div>
                    ))
                  )}
                </div>
              ) : (
                /* Chat View */
                <div
                  ref={scrollRef}
                  className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-3.5 py-3.5"
                >
                  {current.activities.length === 0 && !busy ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
                      <ChatIcon className="h-10 w-10 text-neutral-300 dark:text-neutral-700" />
                      <p className="max-w-[15rem] text-pretty text-[13px] leading-relaxed text-neutral-500">
                        {emptyMessage}
                      </p>
                      <div className="flex flex-wrap items-center justify-center gap-1.5">
                        {suggestions.map((q) => (
                          <button
                            key={q}
                            onClick={() => send(q)}
                            className="rounded-full border border-neutral-200 px-3 py-1.5 text-[12px] text-neutral-700 transition-colors hover:bg-neutral-100 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <>
                      {current.activities.map((a) => (
                        <ActivityRow key={a.id} content={a.content} />
                      ))}
                      {thinking && <ThinkingRow />}
                      {!busy &&
                        lastType === "response" &&
                        followUps.sessionId === current.id &&
                        followUps.items.length > 0 && (
                          <FollowUps
                            items={followUps.items}
                            onPick={(q) => send(q)}
                          />
                        )}
                    </>
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
                      placeholder="Ask me anything..."
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          send();
                        }
                      }}
                      className="max-h-24 w-full resize-none bg-transparent text-[13px] leading-relaxed text-neutral-900 outline-none placeholder:text-neutral-400 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                    />
                    <div className="mt-1.5 flex items-center">
                      <div className="flex-1" />
                      <button
                        onClick={() => send()}
                        disabled={!input.trim() || busy}
                        aria-label="Send"
                        className={`grid h-7 w-7 place-items-center rounded-full transition-[background-color,color,scale] active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 ${
                          input.trim() && !busy
                            ? "bg-neutral-900 text-white hover:opacity-90 dark:bg-white dark:text-neutral-900"
                            : "bg-neutral-100 text-neutral-400 dark:bg-neutral-700"
                        }`}
                      >
                        <ArrowUpIcon />
                      </button>
                    </div>
                  </div>
                </div>
              )}
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

function ActivityRow({ content }: { content: Content }) {
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
      <div className="text-[13px] leading-relaxed text-red-500">
        {content.body}
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
        <div className="mt-1.5 flex items-center gap-1 opacity-0 transition-opacity group-hover/resp:opacity-100">
          <CopyButton text={content.text} />
        </div>
      )}
    </motion.div>
  );
}

function ThinkingRow() {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ type: "spring", stiffness: 420, damping: 32 }}
      className="flex items-center gap-1.5"
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
}: {
  items: string[];
  onPick: (q: string) => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
      className="mt-0.5 flex flex-col gap-0.5 border-t border-neutral-200 pt-2.5 dark:border-neutral-800"
    >
      <span className="mb-0.5 px-2 text-[11px] font-medium text-neutral-400">
        Keep exploring
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
          className="group/fu flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] text-neutral-700 transition-colors hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          <span className="flex-1">{q}</span>
          <ArrowUpRightIcon className="h-3.5 w-3.5 shrink-0 text-neutral-400 transition-colors group-hover/fu:text-neutral-700 dark:group-hover/fu:text-neutral-300" />
        </motion.button>
      ))}
    </motion.div>
  );
}

function CopyButton({ text }: { text: string }) {
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
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
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
      {copied ? "Copied" : "Copy"}
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
      className={`grid h-7 w-7 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 ${
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

function relativeTime(t: number): string {
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86_400)}d`;
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
