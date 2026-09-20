"""
Рендеринг Markdown-ответов LLM под Telegram.

Telegram не понимает GitHub-таблицы и заголовки `###`, поэтому вердикт роя
конвертируется в HTML Telegram:
  - Markdown-таблицы -> выровненная моноширинная таблица в <pre>;
  - ### Заголовок    -> <b>Заголовок</b>;
  - **жирный**       -> <b>жирный</b>;
  - остальной текст экранируется (html.escape).
"""
import html
import re
import unicodedata


def _display_width(s: str) -> int:
    """Видимая ширина строки: широкие символы (эмодзи, CJK) считаются за 2."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _render_table(rows: list[list[str]]) -> str:
    """Markdown-таблица -> выровненный ASCII-вид в <pre>."""
    # Внутри <pre> Telegram-форматирование не работает — снимаем **жирный**
    rows = [[c.replace("**", "").strip() for c in r] for r in rows if any(c.strip() for c in r)]
    # Удаляем разделительную строку вида ---|---
    rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "---") for c in r)]
    if not rows:
        return ""
    n_cols = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (n_cols - len(r)))
    widths = [max(_display_width(r[i]) for r in rows) for i in range(n_cols)]

    def line(l: str, m: str, rr: str) -> str:
        return l + m.join("─" * (w + 2) for w in widths) + rr

    def fmt(r: list[str]) -> str:
        cells = []
        for i, c in enumerate(r):
            pad = widths[i] - _display_width(c)
            cells.append(f" {c}{' ' * pad} ")
        return "│" + "│".join(cells) + "│"

    out = [line("┌", "┬", "┐"), fmt(rows[0]), line("├", "┼", "┤")]
    out += [fmt(r) for r in rows[1:]]
    out.append(line("└", "┴", "┘"))
    return "<pre>" + "\n".join(out) + "</pre>"


def render_for_telegram(text: str) -> str:
    """Конвертирует LLM-ответ в HTML для Telegram (tables, заголовки, жирный)."""
    lines = text.split("\n")
    out: list[str] = []
    table_buf: list[list[str]] = []

    def flush_table():
        nonlocal table_buf
        if table_buf:
            rendered = _render_table(table_buf)
            if rendered:
                out.append(rendered)
            table_buf = []

    for line in lines:
        if line.strip().startswith("|"):
            table_buf.append(line.strip().strip("|").split("|"))
            continue
        flush_table()
        s = line.rstrip()
        # Заголовки ###/##/#  -> жирный
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            out.append(f"<b>{html.escape(m.group(2).strip())}</b>")
            continue
        s = html.escape(s)
        # **жирный** -> <b>жирный</b> (пары)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        out.append(s)
    flush_table()
    return "\n".join(out)
