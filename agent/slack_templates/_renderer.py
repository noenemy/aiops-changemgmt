"""Mustache-lite template renderer for Slack Block Kit.

Supports:
  {{var}}            — substitute context[var], empty string if missing
  {{#if var}}...{{/if}} — include block only if var is truthy
  {{#each var}}...{{/each}} — iterate var (list of dicts). Inside, each item's
                              keys are exposed as {{.field}} (dot-prefixed) and
                              {{index}} is 1-based
  {{>sections/xxx}}  — include file sections/xxx.json (raw JSON object or array)

After rendering, the result is parsed as JSON and the `blocks` array returned.
Commas between iterated blocks are joined automatically.
"""

from __future__ import annotations

import json
import os
import re

_TEMPLATE_DIR = os.path.dirname(__file__)
_EACH_RE = re.compile(r"\{\{#each\s+([a-zA-Z_][\w]*)\s*\}\}(.*?)\{\{/each\}\}", re.DOTALL)
_IF_RE = re.compile(r"\{\{#if\s+([a-zA-Z_][\w]*)\s*\}\}(.*?)\{\{/if\}\}", re.DOTALL)
_IF_DOT_RE = re.compile(r"\{\{#if\s+\.([a-zA-Z_][\w]*)\s*\}\}(.*?)\{\{/if\}\}", re.DOTALL)
_INCLUDE_RE = re.compile(r"\{\{>\s*([a-zA-Z0-9_/\-\.]+)\s*\}\}")
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w]*)\s*\}\}")
_ITEM_VAR_RE = re.compile(r"\{\{\s*\.([a-zA-Z_][\w]*)\s*\}\}")


def _read(name: str) -> str:
    path = os.path.join(_TEMPLATE_DIR, name)
    if not path.endswith(".json"):
        path += ".json"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _resolve_includes(text: str, depth: int = 0) -> str:
    if depth > 4:
        raise RuntimeError("Include depth exceeded (cycle?)")

    def repl(m):
        inner = _read(m.group(1))
        inner = _resolve_includes(inner, depth + 1)
        # Strip trailing newline to keep JSON compact
        return inner.rstrip("\n")

    return _INCLUDE_RE.sub(repl, text)


def _apply_each(text: str, ctx: dict) -> str:
    """Expand {{#each var}}...{{/each}} where ctx[var] is a list of dicts.

    Each item's rendered chunk keeps its own leading/trailing punctuation
    (usually a leading `,`). Join is plain concatenation so the template
    author controls the comma placement by writing e.g.

        {{#each issues}},
        {{>sections/issue_item}}
        {{/each}}

    That template produces `,<block>,<block>,<block>` for 3 items and an
    empty string for 0 items — which keeps the surrounding JSON valid.
    """

    def repl(m):
        var = m.group(1)
        body = m.group(2)
        items = ctx.get(var) or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        rendered = []
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            chunk = body
            def if_dot_repl(mm):
                k = mm.group(1)
                return mm.group(2) if item.get(k) else ""
            prev = None
            while prev != chunk:
                prev = chunk
                chunk = _IF_DOT_RE.sub(if_dot_repl, chunk)
            chunk = _ITEM_VAR_RE.sub(
                lambda mm: _escape_for_json(item.get(mm.group(1), "")), chunk
            )
            chunk = chunk.replace("{{index}}", str(i))
            rendered.append(chunk)
        return "".join(rendered)

    prev = None
    while prev != text:
        prev = text
        text = _EACH_RE.sub(repl, text)
    return text


def _apply_conditionals(text: str, ctx: dict) -> str:
    def repl(m):
        var = m.group(1)
        body = m.group(2)
        return body if ctx.get(var) else ""

    prev = None
    while prev != text:
        prev = text
        text = _IF_RE.sub(repl, text)
    return text


def _escape_for_json(s: str) -> str:
    """Escape control chars/quotes for safe JSON string embedding."""
    if not isinstance(s, str):
        s = str(s)
    return json.dumps(s, ensure_ascii=False)[1:-1]  # strip surrounding quotes


def _substitute_vars(text: str, ctx: dict) -> str:
    def repl(m):
        key = m.group(1)
        val = ctx.get(key, "")
        return _escape_for_json(val)

    return _VAR_RE.sub(repl, text)


def render_template(template_name: str, ctx: dict) -> list:
    """Render template to Slack `blocks` list.

    Order:
      1. includes  (so included text participates in conditionals & vars)
      2. conditionals
      3. variable substitution
      4. JSON parse
    """
    raw = _read(template_name)
    raw = _resolve_includes(raw)
    raw = _apply_each(raw, ctx)
    raw = _apply_conditionals(raw, ctx)
    raw = _substitute_vars(raw, ctx)

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Rendered template is not valid JSON: {e}\n---\n{raw}") from e

    if isinstance(obj, dict) and "blocks" in obj:
        return obj["blocks"]
    if isinstance(obj, list):
        return obj
    raise ValueError(f"Template {template_name} must return {{blocks: [...]}} or a list")
