import re


def split_text(text, size, overlap):
    """Character windows, preferring paragraph ends. Offsets index decoded Python text."""
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError('Invalid chunk settings')
    boundaries = [match.end() for match in re.finditer(r'\n\s*\n', text)]
    headings = [(match.start(), match.group(0).strip().lstrip('#').strip()[:255])
                for match in re.finditer(r'(?m)^#{1,6}\s+[^\n]+', text)]
    start, ordinal = 0, 0
    while start < len(text):
        limit = min(start + size, len(text))
        candidates = [b for b in boundaries if start + size // 2 <= b <= limit]
        end = max(candidates) if candidates else limit
        if not text[start:end].strip():
            start = end
            continue
        heading = next((h for p, h in reversed(headings) if p <= start), '')
        paragraph = 1 + sum(1 for b in boundaries if b <= start)
        yield {'ordinal': ordinal, 'content': text[start:end], 'heading': heading,
               'paragraph_number': paragraph, 'char_start': start, 'char_end': end}
        ordinal += 1
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
