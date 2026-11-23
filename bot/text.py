import html

MAX_LEN = 4000


def esc(value):
    return html.escape(str(value or ""), quote=False)


def for_speech(text, limit=200):
    """Réduit un texte à ce qui sera prononcé : 2 phrases courtes maximum."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > 60:
            return cut[:idx + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def chunk(text, limit=MAX_LEN):
    text = text or ""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n"):
        if len(current) + len(block) + 1 > limit:
            if current:
                parts.append(current)
                current = ""
            while len(block) > limit:
                parts.append(block[:limit])
                block = block[limit:]
        current = f"{current}\n{block}" if current else block
    if current:
        parts.append(current)
    return parts


async def send_long(message, text, keyboard=None, parse_mode="HTML"):
    parts = chunk(text)
    for index, part in enumerate(parts):
        await message.reply_text(
            part,
            parse_mode=parse_mode,
            reply_markup=keyboard if index == len(parts) - 1 else None,
        )


async def edit_long(callback_query, text, keyboard=None, parse_mode="HTML"):
    parts = chunk(text)
    await callback_query.edit_message_text(
        parts[0], parse_mode=parse_mode,
        reply_markup=keyboard if len(parts) == 1 else None,
    )
    for index, part in enumerate(parts[1:], start=1):
        await callback_query.message.reply_text(
            part, parse_mode=parse_mode,
            reply_markup=keyboard if index == len(parts) - 1 else None,
    )
