"""Formatter for MuninnDB recall results."""


def format_recall_result(result: dict, max_tokens: int = 800) -> str:
    """Format MuninnDB recall result into a compact context block."""
    memories = (
        result.get("memories") or result.get("engrams") or result.get("results") or []
    )
    if not memories:
        return ""

    lines = ["[MuninnDB Context]"]
    char_budget = max_tokens * 4  # rough token-to-char estimate
    total = 0

    for m in memories[:10]:
        concept = m.get("concept", "")
        summary = m.get("summary") or m.get("content", "")
        if not summary:
            continue
        # Compact
        summary = summary.replace("\n", " ").strip()[:300]
        line = f"- {concept}: {summary}" if concept else f"- {summary}"
        if total + len(line) > char_budget:
            break
        lines.append(line)
        total += len(line)

    return "\n".join(lines) if len(lines) > 1 else ""
