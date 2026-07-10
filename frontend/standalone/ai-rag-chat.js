/*
 * AI RAG Chat — browser-ready, dependency-free Web Component.
 *
 * <script src="/path/to/ai-rag-chat.js" defer></script>
 * <ai-rag-chat api-base="https://api.example.com" label="Ask me anything" language="en"></ai-rag-chat>
 *
 * Optional: storage="local" (default), "session", or "none".
 */
(function () {
  "use strict";

  if (typeof window === "undefined" || !window.customElements || customElements.get("ai-rag-chat")) return;

  var MAX_CHARS = 4000;
  var MAX_MESSAGES = 40; // 20 complete user/assistant turns.
  var MAX_SESSIONS = 10; // Keeps worst-case localStorage below typical browser quotas.
  var COPY = {
    en: {
      assistant: "AI assistant", dialog: "AI chat", history: "History", newChat: "New chat",
      close: "Close chat", open: "Open chat", placeholder: "Ask a question…", send: "Send message", stop: "Stop generating",
      empty: "Ask about my work, experience, or projects.", suggestions: ["What do you work on?", "Tell me about your experience", "What is your approach to your work?"],
      you: "You", thinking: "Thinking…", copy: "Copy", copied: "Copied", retry: "Retry",
      connectionError: "The response was interrupted. Your partial answer is still here.", requestError: "I couldn't reach the chat service. Please try again.",
      followUps: "Keep exploring", savedLocal: "Saved on this device", savedSession: "Saved for this browser tab", notSaved: "Not saved", noHistory: "No conversations yet.",
      clear: "Clear history", clearConfirm: "Clear all saved conversations?", latest: "Back to latest", responseComplete: "Response complete.", responseStopped: "Response stopped.",
      characterCount: "characters", source: "Sources", historyLabel: "Open conversation history", scrollLabel: "Jump to latest message"
    },
    zh: {
      assistant: "AI 助手", dialog: "AI 对话", history: "历史记录", newChat: "新对话",
      close: "关闭对话", open: "打开对话", placeholder: "输入你的问题…", send: "发送消息", stop: "停止生成",
      empty: "欢迎询问我的工作、经历或项目。", suggestions: ["你从事什么工作？", "介绍一下你的经历", "你的工作方法是什么？"],
      you: "你", thinking: "正在思考…", copy: "复制", copied: "已复制", retry: "重试",
      connectionError: "回复已中断，已保留当前内容。", requestError: "暂时无法连接聊天服务，请重试。",
      followUps: "继续探索", savedLocal: "保存在此设备上", savedSession: "仅保存在此浏览器标签页", notSaved: "不会保存", noHistory: "还没有对话记录。",
      clear: "清除历史记录", clearConfirm: "要清除所有已保存的对话吗？", latest: "回到最新消息", responseComplete: "回复完成。", responseStopped: "回复已停止。",
      characterCount: "个字符", source: "来源", historyLabel: "打开对话历史", scrollLabel: "跳至最新消息"
    }
  };

  function uid() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
    return "ai-rag-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  function icon(path) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="' + path + '" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  var ICON = {
    chat: icon("M20 11.5a7.5 7.5 0 0 1-7.5 7.5H8l-4 3v-5.2A7.5 7.5 0 1 1 20 11.5Z"),
    close: icon("m7 7 10 10M17 7 7 17"),
    plus: icon("M12 5v14M5 12h14"),
    history: icon("M3.5 12a8.5 8.5 0 1 0 2.5-6M3.5 4v4h4M12 7v5l3.5 2"),
    send: icon("m5 12 14-7-4 14-3-5-7-2Z"),
    copy: icon("M9 9h10v10H9zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"),
    check: icon("m5 12 4.2 4L19 6"),
    down: icon("m7 10 5 5 5-5")
  };

  function safeSources(raw) {
    if (!raw) return [];
    try { raw = JSON.parse(raw); } catch (_) { return []; }
    if (!Array.isArray(raw)) return [];
    return raw.slice(0, 3).map(function (entry) {
      var item = typeof entry === "string" ? { title: entry } : entry || {};
      var href = typeof item.url === "string" ? item.url : "";
      try {
        var url = new URL(href, window.location.href);
        href = /^(https?):$/.test(url.protocol) ? url.href : "";
      } catch (_) { href = ""; }
      return { title: String(item.title || item.name || item.file || href || "Source").slice(0, 240), href: href };
    }).filter(function (item) { return item.title; });
  }

  function compactTitle(text) {
    var clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > 42 ? clean.slice(0, 42) + "…" : clean;
  }

  function boundedHistory(messages) {
    var bounded = messages.slice(-MAX_MESSAGES);
    if (bounded[0] && bounded[0].role === "assistant") bounded.shift();
    return bounded;
  }

  function relativeTime(timestamp, language) {
    var seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (language === "zh") {
      if (seconds < 60) return "刚刚";
      if (seconds < 3600) return Math.floor(seconds / 60) + " 分钟前";
      if (seconds < 86400) return Math.floor(seconds / 3600) + " 小时前";
      return Math.floor(seconds / 86400) + " 天前";
    }
    if (seconds < 60) return "just now";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h";
    return Math.floor(seconds / 86400) + "d";
  }

  class AiRagChat extends HTMLElement {
    static get observedAttributes() { return ["api-base", "label", "language", "storage", "storage-key"]; }

    constructor() {
      super();
      this._root = this.attachShadow({ mode: "open" });
      this._connected = false;
      this._bound = false;
      this._frame = 0;
      this._abortController = null;
      this._activeRequest = null;
      this._requestId = 0;
      this._copiedId = "";
      this._lastRequest = null;
      this._sessions = [];
      this._activeId = "";
      this._state = { open: false, view: "chat", input: "", busy: false, followups: [], error: null, stickToBottom: true };
      this._restore();
      this._ensureSession();
    }

    connectedCallback() {
      this._connected = true;
      this._renderShell();
      this._bind();
      this._renderAll();
    }

    disconnectedCallback() {
      this._connected = false;
      this._stopRequest(false);
      if (this._frame) cancelAnimationFrame(this._frame);
      this._frame = 0;
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (oldValue === newValue || !this._connected) return;
      if (name === "api-base" || name === "storage" || name === "storage-key") {
        this._stopRequest(false);
        this._restore();
        this._ensureSession();
      }
      this._renderAll();
    }

    get apiBase() {
      var base = (this.getAttribute("api-base") || "").trim().replace(/\/+$/, "");
      return base === "/api" ? "" : base.endsWith("/api") ? base.slice(0, -4) : base;
    }
    get language() {
      var value = this.getAttribute("language") || (navigator.language || "en");
      return /^zh/i.test(value) ? "zh" : "en";
    }
    get copy() { return COPY[this.language]; }
    get storageMode() {
      var mode = (this.getAttribute("storage") || "local").toLowerCase();
      return mode === "session" || mode === "none" ? mode : "local";
    }
    get activeSession() { return this._sessions.find((session) => session.id === this._activeId) || this._sessions[0]; }

    /** Opens the widget and focuses the composer. */
    open() {
      this._state.open = true;
      this._state.view = "chat";
      this._renderAll();
      var self = this;
      requestAnimationFrame(function () { if (self._els && self._els.input) self._els.input.focus(); });
    }

    /** Stops an active response, closes the widget, and returns focus to its launcher. */
    close() {
      this._stopRequest(true);
      this._state.open = false;
      this._renderAll();
      var self = this;
      requestAnimationFrame(function () { if (self._els && self._els.fab) self._els.fab.focus(); });
    }

    /** Sends a message programmatically. Returns false while a response is in progress. */
    send(text) { return this._send(text == null ? this._state.input : text); }

    /** Clears browser-stored conversations for this component. */
    clearHistory() { this._clearHistory(); }

    _storageKey() {
      return "ai-rag-chat:v1:" + (this.getAttribute("storage-key") || this.id || this.apiBase || window.location.pathname);
    }

    _store() {
      try { return this.storageMode === "local" ? window.localStorage : this.storageMode === "session" ? window.sessionStorage : null; } catch (_) { return null; }
    }

    _ensureSession() {
      if (!this._sessions.length) {
        var now = Date.now();
        this._sessions = [{ id: uid(), title: "", createdAt: now, updatedAt: now, messages: [] }];
      }
      if (!this._sessions.some((session) => session.id === this._activeId)) this._activeId = this._sessions[0].id;
    }

    _restore() {
      this._sessions = [];
      this._activeId = "";
      var store = this._store();
      if (!store) return;
      try {
        var saved = JSON.parse(store.getItem(this._storageKey()) || "null");
        if (!saved || !Array.isArray(saved.sessions)) return;
        this._sessions = saved.sessions.slice(0, MAX_SESSIONS).map(function (session) {
          var messages = Array.isArray(session.messages) ? session.messages.slice(-MAX_MESSAGES).map(function (message) {
            return {
              id: String(message.id || uid()), role: message.role === "assistant" ? "assistant" : "user",
              text: String(message.text || "").slice(0, MAX_CHARS), createdAt: Number(message.createdAt) || Date.now(),
              sources: safeSources(JSON.stringify(Array.isArray(message.sources) ? message.sources : []))
            };
          }).filter(function (message) { return message.text; }) : [];
          return { id: String(session.id || uid()), title: String(session.title || "").slice(0, 80), createdAt: Number(session.createdAt) || Date.now(), updatedAt: Number(session.updatedAt) || Date.now(), messages: messages };
        });
        this._activeId = typeof saved.activeId === "string" ? saved.activeId : "";
      } catch (_) { this._sessions = []; }
    }

    _save() {
      var store = this._store();
      if (!store) return;
      try {
        store.setItem(this._storageKey(), JSON.stringify({ activeId: this._activeId, sessions: this._sessions.slice(0, MAX_SESSIONS).map(function (session) {
          return { id: session.id, title: session.title, createdAt: session.createdAt, updatedAt: session.updatedAt, messages: session.messages.slice(-MAX_MESSAGES).filter(function (message) { return !message.streaming && message.text; }) };
        }) }));
      } catch (_) { /* Browser storage may be unavailable or full. */ }
    }

    _renderShell() {
      this._root.innerHTML = `
        <style>
          :host { color-scheme: light dark; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
          *, *::before, *::after { box-sizing: border-box; }
          button, textarea { font: inherit; } button { cursor: pointer; } button:disabled { cursor: not-allowed; opacity: .48; }
          button:focus-visible, textarea:focus-visible, .history-item:focus-visible { outline: 3px solid var(--ai-rag-focus, #2563eb); outline-offset: 2px; }
          [hidden] { display: none !important; } .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
          .widget { position: fixed; right: max(16px, env(safe-area-inset-right)); bottom: max(16px, env(safe-area-inset-bottom)); z-index: 2147483000; color: #172033; }
          .fab { min-height: 44px; display: inline-flex; align-items: center; gap: 9px; border: 1px solid rgba(15,23,42,.12); border-radius: 999px; padding: 0 16px; background: var(--ai-rag-accent, #111827); color: #fff; font-size: 14px; font-weight: 650; box-shadow: 0 14px 36px rgba(15,23,42,.22); transition: transform .18s ease, box-shadow .18s ease; }
          .fab:hover { transform: translateY(-1px); box-shadow: 0 18px 44px rgba(15,23,42,.28); } .fab svg { width: 18px; height: 18px; }
          .panel { position: absolute; right: 0; bottom: 0; display: flex; flex-direction: column; width: min(410px, calc(100vw - 32px)); height: min(640px, calc(100dvh - 32px)); overflow: hidden; border: 1px solid rgba(15,23,42,.13); border-radius: 20px; background: var(--ai-rag-panel-bg, #fff); box-shadow: 0 24px 70px rgba(15,23,42,.25); }
          .header { min-height: 60px; display: flex; align-items: center; gap: 6px; padding: 8px 8px 8px 16px; border-bottom: 1px solid #e6e9ee; }
          .title { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; font-weight: 700; } .busy-dot { display: inline-block; width: 7px; height: 7px; margin-left: 6px; border-radius: 50%; background: #2563eb; animation: pulse 1.2s ease infinite; }
          .icon-button { width: 44px; height: 44px; display: grid; place-items: center; flex: 0 0 auto; border: 0; border-radius: 10px; background: transparent; color: #526176; } .icon-button:hover { background: #f0f3f7; color: #172033; } .icon-button[aria-pressed="true"] { background: #eaf0ff; color: #1d4ed8; } .icon-button svg { width: 19px; height: 19px; }
          .chat-view, .history-view { min-height: 0; flex: 1; display: flex; flex-direction: column; } .scroll { min-height: 0; flex: 1; overflow: auto; overscroll-behavior: contain; padding: 18px 16px 12px; }
          .empty { min-height: 100%; display: grid; align-content: center; justify-items: center; gap: 15px; padding: 24px 10px; text-align: center; color: #617087; } .empty svg { width: 42px; height: 42px; color: #aeb8c7; } .empty p { max-width: 270px; margin: 0; font-size: 14px; line-height: 1.55; }
          .chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; } .chip, .followup { min-height: 44px; border: 1px solid #d9e0ea; border-radius: 999px; padding: 7px 12px; background: #fff; color: #334155; font-size: 13px; text-align: left; } .chip:hover, .followup:hover { background: #f3f6fa; }
          .message-list { display: grid; gap: 16px; } .message { display: grid; gap: 6px; max-width: 92%; } .message.user { justify-self: end; } .message.assistant { justify-self: start; width: 100%; } .role { font-size: 12px; font-weight: 700; color: #718096; } .user .role { text-align: right; }
          .bubble { overflow-wrap: anywhere; white-space: pre-wrap; border-radius: 15px; padding: 11px 13px; font-size: 14px; line-height: 1.58; } .user .bubble { background: var(--ai-rag-accent, #111827); color: #fff; border-bottom-right-radius: 4px; } .assistant .bubble { background: #f3f6f9; color: #172033; border-bottom-left-radius: 4px; }
          .typing { display: inline-flex; align-items: center; gap: 5px; min-height: 22px; } .typing i { display: block; width: 6px; height: 6px; border-radius: 50%; background: #758198; animation: bounce 1s ease-in-out infinite; } .typing i:nth-child(2) { animation-delay: .12s; } .typing i:nth-child(3) { animation-delay: .24s; } .cursor { display: inline-block; width: 7px; height: 1.1em; margin-left: 2px; vertical-align: -2px; background: #64748b; animation: blink 1s steps(2, start) infinite; }
          .message-tools { display: flex; align-items: center; gap: 4px; } .copy { min-height: 44px; display: inline-flex; align-items: center; gap: 6px; border: 0; border-radius: 8px; padding: 5px 8px; background: transparent; color: #607087; font-size: 12px; } .copy:hover { background: #e9edf3; color: #253247; } .copy svg { width: 15px; height: 15px; }
          .source-list { display: grid; gap: 5px; margin: 2px 0 0; padding: 9px 10px; border-left: 2px solid #c7d2fe; background: #f8faff; border-radius: 0 8px 8px 0; } .source-list strong { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .05em; } .source-list a, .source-list span { overflow-wrap: anywhere; color: #1d4ed8; font-size: 12px; } .source-list a:hover { text-decoration: underline; }
          .error { display: flex; align-items: center; gap: 10px; margin: 14px 0 4px; padding: 10px 11px; border: 1px solid #fecaca; border-radius: 10px; background: #fff7f7; color: #9f1239; font-size: 13px; line-height: 1.4; } .error span { flex: 1; } .retry { min-height: 44px; border: 1px solid #fda4af; border-radius: 8px; padding: 5px 10px; background: #fff; color: #9f1239; font-weight: 650; }
          .followups { display: grid; gap: 7px; margin-top: 18px; padding-top: 15px; border-top: 1px solid #e6e9ee; } .followups h3 { margin: 0 0 2px; color: #718096; font-size: 12px; font-weight: 700; } .followup { width: 100%; min-height: 44px; border-radius: 10px; }
          .scroll-latest { position: absolute; right: 16px; bottom: 98px; min-height: 44px; border: 1px solid #d9e0ea; border-radius: 999px; padding: 6px 12px; background: #fff; color: #334155; box-shadow: 0 7px 20px rgba(15,23,42,.12); font-size: 12px; font-weight: 650; } .scroll-latest svg { width: 16px; height: 16px; margin-right: 4px; vertical-align: -3px; }
          .composer { display: grid; gap: 7px; padding: 10px 12px max(12px, env(safe-area-inset-bottom)); border-top: 1px solid #e6e9ee; background: #fff; } textarea { width: 100%; min-height: 48px; max-height: 116px; resize: none; border: 1px solid #cdd5df; border-radius: 12px; padding: 12px; background: #fff; color: #172033; font-size: 14px; line-height: 1.4; } textarea::placeholder { color: #8b98a9; } textarea:focus { border-color: #2563eb; outline: 0; box-shadow: 0 0 0 3px rgba(37,99,235,.15); }
          .composer-bottom { min-height: 32px; display: flex; align-items: center; gap: 10px; } .counter { flex: 1; color: #7a8799; font-size: 12px; font-variant-numeric: tabular-nums; } .send { width: 44px; height: 44px; display: grid; place-items: center; border: 0; border-radius: 11px; background: var(--ai-rag-accent, #111827); color: #fff; } .send:hover:not(:disabled) { background: #293548; } .send svg { width: 18px; height: 18px; }
          .history-body { min-height: 0; flex: 1; overflow: auto; padding: 16px; } .history-note { margin: 0 0 12px; color: #718096; font-size: 12px; } .history-list { display: grid; gap: 7px; } .history-item { min-height: 56px; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; border: 1px solid transparent; border-radius: 11px; padding: 9px 10px; background: transparent; color: #172033; text-align: left; } .history-item:hover, .history-item[aria-current="true"] { border-color: #dbe4ef; background: #f5f7fa; } .history-item strong, .history-item small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .history-item strong { font-size: 13px; } .history-item small { color: #7a8799; font-size: 11px; } .clear { width: 100%; min-height: 44px; margin-top: 16px; border: 1px solid #fecaca; border-radius: 10px; background: #fff; color: #b4233c; font-size: 13px; font-weight: 650; }
          @keyframes pulse { 50% { opacity: .25; } } @keyframes bounce { 50% { transform: translateY(-3px); opacity: .45; } } @keyframes blink { 50% { opacity: 0; } }
          @media (max-width: 600px) { .widget { right: 0; bottom: 0; left: 0; } .panel { position: fixed; right: 0; bottom: 0; width: 100vw; height: min(84dvh, 700px); border-right: 0; border-bottom: 0; border-left: 0; border-radius: 20px 20px 0 0; } .fab { position: fixed; right: max(16px, env(safe-area-inset-right)); bottom: max(16px, env(safe-area-inset-bottom)); } .scroll { padding-right: 14px; padding-left: 14px; } }
          @media (prefers-color-scheme: dark) { .panel, .composer { background: var(--ai-rag-panel-bg, #111827); border-color: #293548; } .header, .composer { border-color: #293548; } .title, .bubble, textarea, .history-item { color: #e7edf6; } .icon-button { color: #a9b6c8; } .icon-button:hover { background: #202c3d; color: #fff; } .icon-button[aria-pressed="true"] { background: #1d355f; color: #bfdbfe; } .assistant .bubble, .chip, .followup { background: #1b2636; color: #e7edf6; border-color: #35445a; } .chip:hover, .followup:hover, .copy:hover, .history-item:hover, .history-item[aria-current="true"] { background: #263448; } textarea { border-color: #40516a; background: #172233; } .source-list { background: #172233; } .source-list strong { color: #a9b6c8; } .scroll-latest, .retry, .clear { background: #172233; } .error { background: #311a25; border-color: #7f1d3a; color: #fecdd3; } }
          @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; } }
        </style>
        <div class="widget">
          <button class="fab" type="button" data-action="open">${ICON.chat}<span data-ref="fab-label"></span></button>
          <section class="panel" data-ref="panel" role="dialog" aria-modal="false" aria-labelledby="ai-rag-chat-title" hidden>
            <header class="header"><div class="title" id="ai-rag-chat-title"><span data-ref="title"></span><i class="busy-dot" data-ref="busy-dot" hidden></i></div>
              <button class="icon-button" type="button" data-action="history" data-ref="history-button" aria-pressed="false">${ICON.history}<span class="sr-only" data-ref="history-label"></span></button>
              <button class="icon-button" type="button" data-action="new">${ICON.plus}<span class="sr-only" data-ref="new-label"></span></button>
              <button class="icon-button" type="button" data-action="close">${ICON.close}<span class="sr-only" data-ref="close-label"></span></button>
            </header>
            <div class="chat-view" data-ref="chat-view"><div class="scroll" data-ref="scroll" tabindex="0" role="log" aria-live="off" aria-relevant="additions"><div class="empty" data-ref="empty"></div><div class="message-list" data-ref="messages"></div><div data-ref="followups"></div></div>
              <button class="scroll-latest" type="button" data-action="latest" data-ref="latest" hidden>${ICON.down}<span data-ref="latest-label"></span></button>
              <form class="composer" data-ref="form"><label class="sr-only" data-ref="input-label" for="ai-rag-chat-input"></label><textarea id="ai-rag-chat-input" data-ref="input" maxlength="4000" rows="1"></textarea><div class="composer-bottom"><span class="counter" data-ref="counter"></span><button class="send" data-ref="send" type="submit"><span data-ref="send-icon">${ICON.send}</span><span class="sr-only" data-ref="send-label"></span></button></div></form>
            </div>
            <div class="history-view" data-ref="history-view" hidden><div class="history-body"><p class="history-note" data-ref="history-note"></p><div class="history-list" data-ref="history-list"></div><button class="clear" type="button" data-action="clear" data-ref="clear"></button></div></div>
            <div class="sr-only" data-ref="live" role="status" aria-live="polite"></div>
          </section>
        </div>`;
      this._els = {};
      Array.prototype.forEach.call(this._root.querySelectorAll("[data-ref]"), (element) => { this._els[element.getAttribute("data-ref")] = element; });
      this._els.fab = this._root.querySelector(".fab");
    }

    _bind() {
      if (!this._bound) {
        this._bound = true;
        this._root.addEventListener("click", (event) => {
        var target = event.target.closest("[data-action]");
        if (!target) return;
        var action = target.getAttribute("data-action");
        if (action === "open") this.open();
        if (action === "close") this.close();
        if (action === "history") { this._state.view = this._state.view === "history" ? "chat" : "history"; this._renderAll(); }
        if (action === "new") this._newChat();
        if (action === "latest") this._scrollToLatest(true);
        if (action === "suggestion" || action === "followup") this._send(target.getAttribute("data-question") || "");
        if (action === "retry") this._retry();
        if (action === "copy") this._copyMessage(target.getAttribute("data-message-id"));
        if (action === "session") this._selectSession(target.getAttribute("data-session-id"));
        if (action === "clear") this._clearHistory();
        });
        this._root.addEventListener("input", (event) => {
        if (event.target !== this._els.input) return;
        this._state.input = this._els.input.value.slice(0, MAX_CHARS);
        if (this._els.input.value !== this._state.input) this._els.input.value = this._state.input;
        this._resizeInput();
        this._updateComposer();
        });
        this._root.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && this._state.open) { event.preventDefault(); this.close(); }
        if (event.target === this._els.input && event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); this._send(this._state.input); }
        });
      }
      this._els.form.addEventListener("submit", (event) => { event.preventDefault(); if (this._state.busy) this._stopRequest(true); else this._send(this._state.input); });
      this._els.scroll.addEventListener("scroll", () => {
        var scroll = this._els.scroll;
        this._state.stickToBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 56;
        this._updateLatestButton();
      });
    }

    _renderAll() {
      if (!this._connected || !this._els) return;
      var c = this.copy, session = this.activeSession;
      this._els.fabLabel.textContent = this.getAttribute("label") || c.open;
      this._els.fab.setAttribute("aria-label", c.open);
      this._els.panel.setAttribute("aria-label", c.dialog);
      this._els.title.textContent = this._state.view === "history" ? c.history : (session.title || c.newChat);
      this._els["busy-dot"].hidden = !this._state.busy;
      this._els["history-label"].textContent = c.historyLabel;
      this._els["new-label"].textContent = c.newChat;
      this._els["close-label"].textContent = c.close;
      this._els["history-button"].setAttribute("aria-pressed", String(this._state.view === "history"));
      this._els["chat-view"].hidden = this._state.view !== "chat";
      this._els["history-view"].hidden = this._state.view !== "history";
      this._els.panel.hidden = !this._state.open;
      this._els.fab.hidden = this._state.open;
      this._els["input-label"].textContent = c.placeholder;
      this._els.input.placeholder = c.placeholder;
      this._els["send-label"].textContent = c.send;
      this._els.send.setAttribute("aria-label", c.send);
      this._els["latest-label"].textContent = c.latest;
      this._els.latest.setAttribute("aria-label", c.scrollLabel);
      this._renderMessages();
      this._renderHistory();
      this._updateComposer();
    }

    _renderMessages() {
      if (!this._els) return;
      var session = this.activeSession, c = this.copy, self = this;
      this._els.empty.hidden = session.messages.length > 0;
      this._els.empty.replaceChildren();
      if (!session.messages.length) {
        var introIcon = document.createElement("div"); introIcon.innerHTML = ICON.chat;
        var intro = document.createElement("p"); intro.textContent = c.empty;
        var chips = document.createElement("div"); chips.className = "chips";
        c.suggestions.forEach(function (question) { var button = document.createElement("button"); button.type = "button"; button.className = "chip"; button.dataset.action = "suggestion"; button.dataset.question = question; button.textContent = question; chips.append(button); });
        this._els.empty.append(introIcon, intro, chips);
      }
      this._els.messages.replaceChildren();
      session.messages.forEach(function (message) {
        var row = document.createElement("article"); row.className = "message " + message.role;
        var role = document.createElement("div"); role.className = "role"; role.textContent = message.role === "user" ? c.you : c.assistant;
        var bubble = document.createElement("div"); bubble.className = "bubble";
        if (message.streaming && !message.text) { bubble.innerHTML = '<span class="typing" aria-label="' + c.thinking + '"><i></i><i></i><i></i></span>'; }
        else { bubble.textContent = message.text; if (message.streaming) { var cursor = document.createElement("i"); cursor.className = "cursor"; cursor.setAttribute("aria-hidden", "true"); bubble.append(cursor); } }
        row.append(role, bubble);
        if (message.role === "assistant" && message.text) {
          var tools = document.createElement("div"); tools.className = "message-tools";
          var copy = document.createElement("button"); copy.type = "button"; copy.className = "copy"; copy.dataset.action = "copy"; copy.dataset.messageId = message.id; copy.innerHTML = (self._copiedId === message.id ? ICON.check : ICON.copy) + '<span></span>';
          copy.querySelector("span").textContent = self._copiedId === message.id ? c.copied : c.copy;
          tools.append(copy); row.append(tools);
        }
        if (message.role === "assistant" && message.sources && message.sources.length) {
          var sources = document.createElement("section"); sources.className = "source-list";
          var sourceTitle = document.createElement("strong"); sourceTitle.textContent = c.source; sources.append(sourceTitle);
          message.sources.forEach(function (source) { var item = source.href ? document.createElement("a") : document.createElement("span"); item.textContent = source.title; if (source.href) { item.href = source.href; item.target = "_blank"; item.rel = "noopener noreferrer"; } sources.append(item); });
          row.append(sources);
        }
        self._els.messages.append(row);
      });
      var error = this._state.error;
      if (error && error.sessionId === session.id) {
        var alert = document.createElement("div"); alert.className = "error"; alert.setAttribute("role", "alert");
        var text = document.createElement("span"); text.textContent = error.message;
        var retry = document.createElement("button"); retry.type = "button"; retry.className = "retry"; retry.dataset.action = "retry"; retry.textContent = c.retry;
        alert.append(text, retry); this._els.messages.append(alert);
      }
      this._els.followups.replaceChildren();
      if (!this._state.busy && this._state.followups.length && this._state.followupsSessionId === session.id) {
        var box = document.createElement("section"); box.className = "followups";
        var heading = document.createElement("h3"); heading.textContent = c.followUps; box.append(heading);
        this._state.followups.forEach(function (question) { var button = document.createElement("button"); button.type = "button"; button.className = "followup"; button.dataset.action = "followup"; button.dataset.question = question; button.textContent = question; box.append(button); });
        this._els.followups.append(box);
      }
      this._afterMessageRender();
    }

    _renderHistory() {
      if (!this._els) return;
      var c = this.copy, self = this, sessions = this._sessions.filter(function (session) { return session.messages.length; }).slice().sort(function (a, b) { return b.updatedAt - a.updatedAt; });
      this._els["history-note"].textContent = this.storageMode === "local" ? c.savedLocal : this.storageMode === "session" ? c.savedSession : c.notSaved;
      this._els["history-list"].replaceChildren();
      if (!sessions.length) { var empty = document.createElement("p"); empty.className = "history-note"; empty.textContent = c.noHistory; this._els["history-list"].append(empty); }
      sessions.forEach(function (session) {
        var button = document.createElement("button"); button.type = "button"; button.className = "history-item"; button.dataset.action = "session"; button.dataset.sessionId = session.id; button.setAttribute("aria-current", String(session.id === self._activeId));
        var details = document.createElement("span"), title = document.createElement("strong"), excerpt = document.createElement("small"); title.textContent = session.title || c.newChat; excerpt.textContent = relativeTime(session.updatedAt, self.language); details.append(title, excerpt);
        button.append(details); self._els["history-list"].append(button);
      });
      this._els.clear.textContent = c.clear;
      this._els.clear.hidden = !sessions.length || this.storageMode === "none";
    }

    _updateComposer() {
      if (!this._els) return;
      var input = this._els.input;
      if (input.value !== this._state.input) input.value = this._state.input;
      input.disabled = this._state.busy;
      this._els.send.disabled = !this._state.busy && !this._state.input.trim();
      this._els["send-icon"].innerHTML = this._state.busy ? ICON.close : ICON.send;
      this._els["send-label"].textContent = this._state.busy ? this.copy.stop : this.copy.send;
      this._els.send.setAttribute("aria-label", this._state.busy ? this.copy.stop : this.copy.send);
      this._els.counter.textContent = this._state.input.length + " / " + MAX_CHARS + " " + this.copy.characterCount;
      this._resizeInput();
      this._updateLatestButton();
    }

    _resizeInput() { if (!this._els || !this._els.input) return; var input = this._els.input; input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 116) + "px"; }
    _updateLatestButton() { if (this._els && this._els.latest) this._els.latest.hidden = this._state.stickToBottom || this._state.view !== "chat"; }
    _afterMessageRender() { var self = this; if (this._state.stickToBottom) requestAnimationFrame(function () { self._scrollToLatest(false); }); else this._updateLatestButton(); }
    _scrollToLatest(smooth) { if (!this._els) return; this._state.stickToBottom = true; this._els.scroll.scrollTo({ top: this._els.scroll.scrollHeight, behavior: smooth ? "smooth" : "auto" }); this._updateLatestButton(); }

    _newChat() {
      this._stopRequest(true);
      var now = Date.now(), session = { id: uid(), title: "", createdAt: now, updatedAt: now, messages: [] };
      this._sessions.unshift(session); this._sessions = this._sessions.slice(0, MAX_SESSIONS); this._activeId = session.id; this._state.view = "chat"; this._state.followups = []; this._state.error = null; this._save(); this._renderAll();
      requestAnimationFrame(() => this._els.input.focus());
    }

    _selectSession(id) { if (!this._sessions.some((session) => session.id === id)) return; this._activeId = id; this._state.view = "chat"; this._state.followups = []; this._state.error = null; this._save(); this._renderAll(); requestAnimationFrame(() => this._els.input.focus()); }
    _clearHistory() {
      if (this.storageMode === "none" || !window.confirm(this.copy.clearConfirm)) return;
      var store = this._store(); if (store) { try { store.removeItem(this._storageKey()); } catch (_) {} }
      this._sessions = []; this._activeId = ""; this._ensureSession(); this._state.view = "chat"; this._state.followups = []; this._state.error = null; this._renderAll();
    }

    _send(raw) {
      if (this._state.busy) return false;
      var text = String(raw || "").trim().slice(0, MAX_CHARS);
      if (!text) { if (this._els) this._els.input.focus(); return false; }
      var session = this.activeSession;
      var before = this._apiMessages(session.messages);
      session.messages.push({ id: uid(), role: "user", text: text, createdAt: Date.now() });
      session.messages = boundedHistory(session.messages);
      session.title = session.title || compactTitle(text); session.updatedAt = Date.now();
      this._state.input = ""; this._state.error = null; this._state.followups = []; this._state.followupsSessionId = "";
      var history = boundedHistory(before.concat([{ role: "user", content: text }]));
      this._lastRequest = { sessionId: session.id, history: history };
      this._startResponse(session, history);
      return true;
    }

    _apiMessages(messages) { return boundedHistory(messages.filter(function (message) { return message.text && !message.streaming; }).map(function (message) { return { role: message.role, content: message.text }; })); }
    _message(sessionId, messageId) { var session = this._sessions.find((item) => item.id === sessionId); return session && session.messages.find((item) => item.id === messageId); }

    _startResponse(session, history) {
      var answer = { id: uid(), role: "assistant", text: "", createdAt: Date.now(), streaming: true, sources: [] };
      session.messages.push(answer); session.updatedAt = Date.now(); this._state.busy = true; this._state.stickToBottom = true; this._save(); this._renderAll();
      var requestId = ++this._requestId, controller = new AbortController(); this._abortController = controller; this._activeRequest = { sessionId: session.id, answerId: answer.id };
      this._streamResponse(session.id, answer.id, history, requestId, controller);
    }

    async _streamResponse(sessionId, answerId, history, requestId, controller) {
      try {
        var response = await fetch(this.apiBase + "/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: history, sessionId: sessionId }), signal: controller.signal });
        if (!response.ok || !response.body) throw new Error("request-failed");
        var answer = this._message(sessionId, answerId); if (answer) answer.sources = safeSources(response.headers.get("x-rag-sources"));
        var reader = response.body.getReader(), decoder = new TextDecoder(), result;
        while (!(result = await reader.read()).done) {
          var message = this._message(sessionId, answerId); if (!message || requestId !== this._requestId) return;
          message.text += decoder.decode(result.value, { stream: true }); this._scheduleMessageRender();
        }
        var tail = decoder.decode(); if (tail) { var finalChunk = this._message(sessionId, answerId); if (finalChunk) finalChunk.text += tail; }
        var completed = this._message(sessionId, answerId); if (completed) completed.streaming = false;
        if (requestId !== this._requestId) return;
        this._state.busy = false; this._abortController = null; this._activeRequest = null; this._save(); this._renderAll(); this._announce(this.copy.responseComplete);
        if (completed && completed.text) this._fetchFollowups(sessionId, history.concat([{ role: "assistant", content: completed.text }]), requestId);
      } catch (error) {
        if (controller.signal.aborted || requestId !== this._requestId) return;
        var partial = this._message(sessionId, answerId);
        if (partial) {
          partial.streaming = false;
          if (!partial.text) {
            var failedSession = this._sessions.find((item) => item.id === sessionId);
            if (failedSession) failedSession.messages = failedSession.messages.filter((item) => item.id !== answerId);
          }
        }
        this._state.busy = false; this._abortController = null; this._activeRequest = null; this._state.error = { sessionId: sessionId, answerId: answerId, message: partial && partial.text ? this.copy.connectionError : this.copy.requestError }; this._save(); this._renderAll(); this._announce(this._state.error.message);
      }
    }

    _scheduleMessageRender() {
      if (this._frame) return;
      this._frame = requestAnimationFrame(() => { this._frame = 0; this._renderMessages(); });
    }

    async _fetchFollowups(sessionId, messages, requestId) {
      try {
        var response = await fetch(this.apiBase + "/api/suggest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: boundedHistory(messages), sessionId: sessionId }) });
        if (!response.ok || requestId !== this._requestId) return;
        var data = await response.json();
        if (Array.isArray(data.suggestions)) { this._state.followups = data.suggestions.filter(function (item) { return typeof item === "string" && item.trim(); }).slice(0, 3); this._state.followupsSessionId = sessionId; this._renderMessages(); }
      } catch (_) { /* Suggestions are deliberately non-blocking. */ }
    }

    _stopRequest(announce) {
      if (!this._abortController) return;
      this._abortController.abort(); this._abortController = null; ++this._requestId;
      var request = this._activeRequest;
      var session = request && this._sessions.find((item) => item.id === request.sessionId);
      var last = session && request && this._message(request.sessionId, request.answerId);
      if (last && last.role === "assistant" && last.streaming) { last.streaming = false; if (!last.text) session.messages.pop(); }
      this._activeRequest = null; this._state.busy = false; this._save(); if (this._connected) this._renderAll(); if (announce) this._announce(this.copy.responseStopped);
    }

    _retry() {
      if (this._state.busy || !this._lastRequest) return;
      var failed = this._state.error, session = this._sessions.find((item) => item.id === this._lastRequest.sessionId);
      if (!session) return;
      if (failed) session.messages = session.messages.filter((message) => message.id !== failed.answerId);
      this._state.error = null; this._activeId = session.id; this._state.view = "chat"; this._startResponse(session, this._lastRequest.history);
    }

    async _copyMessage(id) {
      var session = this.activeSession, message = session && session.messages.find(function (item) { return item.id === id; }); if (!message || !message.text) return;
      try { await navigator.clipboard.writeText(message.text); this._copiedId = id; this._renderMessages(); setTimeout(() => { if (this._copiedId === id) { this._copiedId = ""; this._renderMessages(); } }, 1400); } catch (_) { this._announce(this.copy.requestError); }
    }

    _announce(text) { if (this._els && this._els.live) this._els.live.textContent = text; }

    static selfCheck() { return { defined: customElements.get("ai-rag-chat") === AiRagChat, maxCharacters: MAX_CHARS, maxMessages: MAX_MESSAGES }; }
  }

  customElements.define("ai-rag-chat", AiRagChat);
}());
