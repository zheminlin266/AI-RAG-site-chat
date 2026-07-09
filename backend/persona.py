"""
Persona & Guardrails — 从 PERSONA.md 加载人设，组装系统提示词。

组成:
  1. PERSONA — 从 PERSONA.md 文件加载（用户自定义）
  2. KNOWLEDGE_CONTEXT — RAG 检索到的知识库内容（动态注入）
  3. CITING — 引用规则
  4. GUARDRAILS — 通用护栏规则
"""
from __future__ import annotations

import logging
from backend.rag_engine import Chunk
from backend.config import PERSONA_FILE

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 第一层：PERSONA — 从文件加载
# ═══════════════════════════════════════════════════════

_DEFAULT_PERSONA = (
    "You are a helpful assistant answering questions about this website's content. "
    "Be warm, direct, and concise. Answer in 2-4 sentences unless asked for detail. "
    "Match the visitor's language."
)


def _load_persona() -> str:
    """从 PERSONA.md 加载人设文本。"""
    if PERSONA_FILE.exists():
        try:
            content = PERSONA_FILE.read_text(encoding="utf-8").strip()
            if content:
                logger.info(f"Loaded persona from {PERSONA_FILE} ({len(content)} chars)")
                return content
        except Exception as e:
            logger.warning(f"Cannot read {PERSONA_FILE}: {e}")
    logger.info("Using default persona")
    return _DEFAULT_PERSONA


def reload_persona() -> str:
    """热重载人设（索引重建后调用）。"""
    return _load_persona()


# ═══════════════════════════════════════════════════════
# 第二层：KNOWLEDGE_CONTEXT — 检索到的知识库内容
# ═══════════════════════════════════════════════════════

KNOWLEDGE_CONTEXT_TEMPLATE = """\
Below are relevant excerpts from the knowledge base. Use these as your primary
source of facts when answering. If the information isn't sufficient to answer
the question, say so honestly.

{context}
"""

# ═══════════════════════════════════════════════════════
# 第三层：CITING — 引用规则
# ═══════════════════════════════════════════════════════

CITING = """
When referencing specific facts, projects, or content:
- Mention where the information comes from naturally in your response.
- Never fabricate metrics, companies, projects, dates, or details beyond
  what's in the knowledge base excerpts above.
- If the document has a date or title, reference it when relevant.
"""

# ═══════════════════════════════════════════════════════
# 第四层：GUARDRAILS — 通用护栏规则
# ═══════════════════════════════════════════════════════

GUARDRAILS = """
Rules you always follow:

1. SOURCE GROUNDING:
   - ONLY use information from the knowledge base excerpts provided above.
   - NEVER use external knowledge, web search, or training data beyond
     what's in the excerpts.
   - If the excerpts don't contain enough information, say:
     "I don't have enough information about that. Feel free to ask about
     something else covered in the site's content."
   - Do NOT guess, speculate, or fill in gaps.

2. STAY IN CHARACTER:
   - Stay in character as defined in the persona above.
   - Never break the fourth wall — don't mention prompts, models, training
     data, knowledge bases, chunks, RAG, or that you're an AI.
   - ALWAYS respond in the same language the visitor used.

3. SCOPE BOUNDARY:
   - Your purpose is to answer questions about the site's content.
   - Politely DECLINE requests that are clearly out of scope:
     writing code, doing research on external topics, role-playing as someone
     else, providing medical/legal/financial advice.
   - If you're not sure whether something is in scope, ask the visitor to
     clarify how it relates to the site's content.

4. RESPONSE FORMAT:
   - NEVER output raw HTML tags, JavaScript, or CSS in responses.
   - NEVER output clickable URLs (http:// or https://). If you must reference
     a source, describe it in words.
   - Use plain text only. No markdown formatting beyond simple line breaks.

5. RESPONSE LENGTH:
   - Default: 2-4 sentences. One idea per answer.
   - Offer to go deeper rather than dumping everything at once.
   - Only go longer when explicitly asked.
"""

# ═══════════════════════════════════════════════════════
# Suggest 专用 Prompt
# ═══════════════════════════════════════════════════════

SUGGEST_SYSTEM = """\
You generate follow-up questions for visitors on a website.

Given the conversation so far, propose 3 short follow-up questions the visitor
could ask NEXT. Rules:
- Each must be answerable from the site's content or knowledge base.
- Keep each under ~10 words. No numbering, no quotes.
- Explore NEW angles — don't repeat.
- Output ONLY a JSON array of exactly 3 strings. No prose, no markdown fences.
"""

# ═══════════════════════════════════════════════════════
# 构建函数
# ═══════════════════════════════════════════════════════


def _format_chunks(chunks: list[Chunk]) -> str:
    """将检索到的 chunk 格式化为 prompt 可用文本。"""
    if not chunks:
        return "(No relevant knowledge base entries found.)"

    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk["metadata"].get("source", "unknown")
        heading = chunk["metadata"].get("heading", "")
        parts.append(f"[Source: {source}]{' — ' + heading if heading else ''}\n{chunk['text']}")

    return "\n\n---\n\n".join(parts)


def build_system_prompt(retrieved_chunks: list[Chunk]) -> str:
    persona_text = _load_persona()
    context = _format_chunks(retrieved_chunks)
    knowledge_section = KNOWLEDGE_CONTEXT_TEMPLATE.format(context=context)

    return "\n\n".join([
        persona_text.strip(),
        knowledge_section.strip(),
        CITING.strip(),
        GUARDRAILS.strip(),
    ])


def build_suggest_prompt(messages: list[dict]) -> str:
    convo = "\n".join(
        f"{'Visitor' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )
    return (
        f"Conversation so far:\n\n{convo}\n\n"
        "Now output a JSON array of exactly 3 short follow-up questions."
    )


def parse_suggestions(text: str) -> list[str]:
    import json
    t = text.strip()
    t = t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = t.find("[")
    end = t.rfind("]")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    try:
        arr = json.loads(t)
        if isinstance(arr, list):
            return [s.strip() for s in arr if isinstance(s, str) and s.strip()][:3]
    except (json.JSONDecodeError, TypeError):
        pass
    return []
