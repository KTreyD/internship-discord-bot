import html as html_lib
import re

_TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(raw_html: str) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", raw_html)).strip()
