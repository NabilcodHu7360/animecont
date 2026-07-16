"""
fandom.py — Turn a Fandom wiki page into Passage objects via the MediaWiki API.

WHY THIS, NOT SCRAPING
Fandom runs on MediaWiki, which exposes a real API at
    https://<wiki>.fandom.com/api.php
That's structured and stable, versus regex-guessing HTML that breaks on redesign.

The network call and the parsing are kept SEPARATE on purpose:
  - fetch_page_html()  does I/O (needs internet; can't run in a unit test)
  - html_to_passages() is pure (fully testable offline, no network)
This split is why we can prove the parsing works without ever hitting Fandom.

OUTPUT: the SAME Passage type your corpus loader produces, so the retriever and
eval consume it with zero changes.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..grounding.corpus import Passage

FANDOM_API = "https://{wiki}.fandom.com/api.php"

# Sections that are never plot content — skip them. Expanded after inspecting a
# real Steel Ball Run page: the "Characters & Stands" grid (~40 name/stand cards),
# "Major Battles" list, and "Videos" are noise, not narrative.
_SKIP_SECTIONS = {
    "references", "gallery", "trivia", "navigation", "site navigation",
    "external links", "see also", "notes",
    "characters & stands", "characters and stands", "major battles",
    "videos", "chapter list", "media",
}


def fandom_api_url(wiki: str) -> str:
    """'attackontitan' -> 'https://attackontitan.fandom.com/api.php'."""
    return FANDOM_API.format(wiki=wiki)


def fetch_page_html(wiki: str, page: str, timeout: int = 10) -> str:
    """Fetch a page's rendered HTML via action=parse. (Does network I/O.)

    Kept thin so the testable logic lives in html_to_passages().
    """
    import requests
    resp = requests.get(
        fandom_api_url(wiki),
        params={"action": "parse", "page": page, "prop": "text", "format": "json"},
        headers={"User-Agent": "AnimeCont/0.1 (portfolio project)"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(f"Fandom API error for {page!r}: {data['error']}")
    return data["parse"]["text"]["*"]


def _clean(text: str) -> str:
    """Drop citation superscripts like [1], collapse whitespace."""
    text = re.sub(r"\[\d+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def html_to_passages(html: str, series: str, page: str) -> list[Passage]:
    """Parse rendered wiki HTML into one Passage per section. (Pure, testable.)

    A section = an <h2>/<h3> heading plus the paragraphs beneath it, up to the
    next heading. Each Passage carries meta {series, source, page, section} so
    its citation traces back to a real wiki section.
    """
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("div", class_="mw-parser-output") or soup

    passages: list[Passage] = []
    cur_section = "Overview"
    buf: list[str] = []

    def flush():
        if cur_section.lower() in _SKIP_SECTIONS:
            return
        body = _clean(" ".join(buf))
        if len(body.split()) >= 8:  # ignore near-empty stubs
            passages.append(Passage(
                text=body,
                title=cur_section,
                meta={"series": series, "source": "fandom",
                      "page": page, "section": cur_section},
            ))

    for el in root.find_all(["h2", "h3", "p"], recursive=True):
        if el.name in ("h2", "h3"):
            flush()
            # Heading text sits in a <span class="mw-headline"> on MediaWiki.
            headline = el.find("span", class_="mw-headline")
            cur_section = _clean(headline.get_text() if headline else el.get_text())
            buf = []
        else:  # <p>
            txt = _clean(el.get_text())
            if txt:
                buf.append(txt)
    flush()
    return passages


def ingest_page(wiki: str, page: str, series: str | None = None) -> list[Passage]:
    """Convenience: fetch + parse. `series` defaults to the wiki name."""
    html = fetch_page_html(wiki, page)
    return html_to_passages(html, series or wiki, page)

_CHAPTER_KEEP = {"summary", "plot", "plot details", "synopsis", "overview", "events"}
MIN_CHAPTER_WORDS = 40


def chapter_html_to_passage(html: str, series: str, chapter: int):
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("div", class_="mw-parser-output") or soup
    keep_text, grabbing = [], False
    for el in root.find_all(["h2", "h3", "p"], recursive=True):
        if el.name in ("h2", "h3"):
            headline = el.find("span", class_="mw-headline")
            name = _clean(headline.get_text() if headline else el.get_text()).lower()
            grabbing = name in _CHAPTER_KEEP
        elif grabbing:
            txt = _clean(el.get_text())
            if txt:
                keep_text.append(txt)
    body = " ".join(keep_text)
    if len(body.split()) < MIN_CHAPTER_WORDS:
        return None
    return Passage(text=body, title=f"Chapter {chapter}",
                   meta={"series": series, "source": "fandom",
                         "page": f"Chapter_{chapter}", "ch": str(chapter)})


def ingest_chapter_range(wiki, series, start, end, fetch=fetch_page_html):
    passages, kept, skipped = [], 0, 0
    for ch in range(start, end + 1):
        try:
            html = fetch(wiki, f"Chapter_{ch}")
        except Exception:
            skipped += 1
            continue
        p = chapter_html_to_passage(html, series, ch)
        if p:
            passages.append(p); kept += 1
        else:
            skipped += 1
    print(f"    chapters {start}-{end}: kept {kept}, skipped {skipped} (stubs/missing)")
    return passages