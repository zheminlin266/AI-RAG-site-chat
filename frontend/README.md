# Frontend integration

This repository ships two frontend surfaces:

- `ai-chat.tsx`: copy-in React component for React 18+, Tailwind CSS, and Framer Motion.
- `standalone/ai-rag-chat.js`: browser-ready, zero-dependency Web Component for any static site.

## Standalone Web Component

Copy `standalone/ai-rag-chat.js` to your site's public assets and load the browser-ready IIFE with a deferred script tag:

```html
<script src="/assets/ai-rag-chat.js" defer></script>
<ai-rag-chat
  api-base="https://chat.example.com"
  label="Ask me anything"
  language="en"
  storage="local"
></ai-rag-chat>
```

The element uses Shadow DOM, so its styles do not depend on the host site. It is responsive, keyboard accessible, supports streamed answers, and enforces the same 4,000-character message limit as the backend.

### Attributes

| Attribute | Default | Meaning |
|---|---|---|
| `api-base` | same origin | Backend origin, without `/api` (for example `https://chat.example.com`) |
| `label` | localized | Floating-button label |
| `language` | browser language | `en` or `zh`/`zh-CN` UI strings |
| `storage` | `local` | `local`, `session`, or `none` for client-side conversation storage |
| `storage-key` | `ai-rag-chat` | Storage key when storage is enabled |

### Methods

```js
const chat = document.querySelector("ai-rag-chat");
chat.open();
chat.send("What does this site cover?");
chat.clearHistory();
chat.close();
```

When the API is on another origin, configure the backend with the exact host-page origin, for example:

```dotenv
CORS_ORIGIN=https://www.example.com
```

Do not use `*`; the backend intentionally rejects wildcard browser access.

## React component

Copy `ai-chat.tsx` into a React 18+ application with Tailwind CSS and Framer Motion. It accepts `apiBase`, `label`, `suggestions`, `emptyMessage`, and a `strings` object for UI localization. The `apiBase` is the backend origin, not `/api`; requests are sent to `${apiBase}/api/chat`.

The React component labels its in-memory conversation picker “This visit”: it deliberately does not write visitor conversations to storage. Use the standalone element when local/session history controls are desired.
