"""Check project-facing Markdown links and image paths offline.

Checks README, reports, the benchmark evidence README, presentation docs, and
asset notes. External URLs are counted but not fetched. Upstream docs/source
and example documentation are outside this presentation check.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parents[1]
PARSER = MarkdownIt("commonmark", {"html": True}).enable("table")


class HTMLReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.anchors: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and key in ("href", "src"):
                self.links.append(value)
            if value and (key == "id" or (tag == "a" and key == "name")):
                self.anchors.add(value)


def document(path: Path):
    tokens = PARSER.parse(path.read_text())
    links = []
    anchors = set()
    duplicates = Counter()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            children = tokens[index + 1].children or []
            label = "".join(t.content for t in children if t.type in ("text", "code_inline", "image"))
            slug = re.sub(r"[^\w\- ]", "", label.lower()).replace(" ", "-")
            number = duplicates[slug]
            duplicates[slug] += 1
            anchors.add(f"{slug}-{number}" if number else slug)
        for child in [token, *(token.children or [])]:
            if child.type == "link_open":
                links.append(child.attrGet("href"))
            elif child.type == "image":
                links.append(child.attrGet("src"))
            elif child.type in ("html_block", "html_inline"):
                html = HTMLReferences()
                html.feed(child.content)
                links.extend(html.links)
                anchors.update(html.anchors)
    return links, anchors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Optional Markdown files relative to the repository")
    args = parser.parse_args()
    defaults = [
        ROOT / "README.md",
        *sorted(p for p in (ROOT / "reports").glob("*.md") if p.name != "resume_notes.md"),
        ROOT / "benchmark/tau3/README.md",
        ROOT / "assets/README.md",
    ]
    paths = [ROOT / p for p in args.paths] if args.paths else defaults
    cache = {}
    failures = []
    local_count = external_count = 0
    for path in paths:
        if not path.is_file():
            failures.append(f"Missing input: {path}")
            continue
        cache.setdefault(path.resolve(), document(path))
        for target in cache[path.resolve()][0]:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                external_count += 1
                continue
            local_count += 1
            destination = (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
            if not destination.exists():
                failures.append(f"{path.relative_to(ROOT)}: missing {target}")
            elif parts.fragment and destination.suffix.lower() == ".md":
                if destination not in cache:
                    cache[destination] = document(destination)
                if unquote(parts.fragment) not in cache[destination][1]:
                    failures.append(f"{path.relative_to(ROOT)}: missing anchor {target}")
    print(
        json.dumps(
            {
                "passed": not failures,
                "documents": len(paths),
                "local_links": local_count,
                "external_links_not_fetched": external_count,
                "failures": failures,
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
