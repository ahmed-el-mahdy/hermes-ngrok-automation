"""
title: Web Research
description: Search the public web, fetch a URL, extract structured content, and save JSON evidence.
version: 2.0.0
"""

import ipaddress
import json
import os
import re
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from pydantic import BaseModel, Field


WORKSPACE = Path("/app/backend/data/hermes_workspace")


class _PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = []
        self.headings = []
        self.links = []
        self.text = []
        self._tag = ""
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        self._tag = tag
        if tag == "a":
            href = dict(attrs).get("href", "").strip()
            if href:
                self.links.append({"text": "", "href": urllib.parse.urljoin(self.base_url, href)})

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        self._tag = ""

    def handle_data(self, data):
        if self._skip:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.text.append(value)
        if self._tag == "title":
            self.title.append(value)
        elif self._tag in {"h1", "h2", "h3"}:
            self.headings.append(value)
        elif self._tag == "a" and self.links:
            self.links[-1]["text"] = (self.links[-1]["text"] + " " + value).strip()


class Tools:
    class Valves(BaseModel):
        timeout: int = Field(default=25, ge=5, le=120)
        max_download_bytes: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
        max_text_chars: int = Field(default=20_000, ge=1_000, le=100_000)
        google_search_model: str = Field(default="gemini-2.5-flash")

    def __init__(self):
        self.valves = self.Valves()
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def _validate_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only public http and https URLs are allowed")
        for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
            address = ipaddress.ip_address(item[4][0])
            if not address.is_global:
                raise ValueError("Private, local, reserved, and link-local URLs are blocked")
        return url

    def _workspace_path(self, path: str) -> Path:
        root = WORKSPACE.resolve()
        target = (root / path.lstrip("/")).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Output path must remain inside the Hermes workspace") from exc
        return target

    def _fetch(self, url: str):
        self._validate_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,application/json"})
        with urllib.request.urlopen(request, timeout=self.valves.timeout) as response:
            final_url = response.geturl()
            self._validate_url(final_url)
            content_type = response.headers.get("content-type", "").lower()
            if not any(kind in content_type for kind in ("text/", "html", "xml", "json")):
                raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")
            raw = response.read(self.valves.max_download_bytes + 1)
            if len(raw) > self.valves.max_download_bytes:
                raise ValueError("Response exceeds download limit")
            charset = response.headers.get_content_charset() or "utf-8"
            return final_url, content_type, raw.decode(charset, errors="replace")

    def search_web(self, query: str, max_results: int = 5) -> str:
        """Search Google through Gemini grounding, with anonymous HTML/RSS fallbacks."""
        try:
            count = max(1, min(int(max_results), 10))
            key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if key:
                endpoint = (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    + urllib.parse.quote(self.valves.google_search_model, safe="")
                    + ":generateContent?key="
                    + urllib.parse.quote(key, safe="")
                )
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": "Search the current public web for: " + query + ". Give a concise factual summary grounded in sources."}]}],
                    "tools": [{"google_search": {}}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500},
                }
                request = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=max(self.valves.timeout, 90)) as response:
                        grounded = json.load(response)
                    candidate = (grounded.get("candidates") or [{}])[0]
                    summary = " ".join(
                        part.get("text", "")
                        for part in (candidate.get("content") or {}).get("parts", [])
                    ).strip()
                    chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
                    results = []
                    seen = set()
                    for chunk in chunks:
                        web = chunk.get("web") or {}
                        url = web.get("uri", "")
                        if url and url not in seen:
                            seen.add(url)
                            results.append({"title": web.get("title", ""), "url": url, "snippet": summary[:1200]})
                    if results:
                        return json.dumps({"status": "ok", "source": "gemini_google_search", "model": self.valves.google_search_model, "query": query, "summary": summary, "results": results[:count]}, indent=2)
                except Exception:
                    pass
            url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
            _, _, body = self._fetch(url)
            results = []
            anchors = re.findall(
                r'<a[^>]*class=["\'][^"\']*result__a[^"\']*["\'][^>]*href=["\'](.*?)["\'][^>]*>(.*?)</a>',
                body,
                flags=re.I | re.S,
            )
            snippets = re.findall(
                r'<(?:a|div)[^>]*class=["\'][^"\']*result__snippet[^"\']*["\'][^>]*>(.*?)</(?:a|div)>',
                body,
                flags=re.I | re.S,
            )
            for index, (href, title_html) in enumerate(anchors[:count]):
                href = unescape(href)
                if href.startswith("//"):
                    href = "https:" + href
                parsed = urllib.parse.urlparse(href)
                if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
                    href = urllib.parse.parse_qs(parsed.query).get("uddg", [href])[0]
                title = " ".join(unescape(re.sub(r"<[^>]+>", " ", title_html)).split())
                snippet_html = snippets[index] if index < len(snippets) else ""
                snippet = " ".join(unescape(re.sub(r"<[^>]+>", " ", snippet_html)).split())
                results.append({"title": title, "url": href, "snippet": snippet})
            source = "duckduckgo_html"
            if not results:
                fallback = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss", "setlang": "en-US", "cc": "US"})
                _, _, body = self._fetch(fallback)
                root = ET.fromstring(body)
                for item in root.findall(".//item")[:count]:
                    snippet = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
                    results.append({"title": unescape(item.findtext("title") or ""), "url": item.findtext("link") or "", "snippet": " ".join(unescape(snippet).split())})
                source = "bing_rss"
            return json.dumps({"status": "ok" if results else "error", "source": source, "query": query, "results": results}, indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "query": query, "error": str(exc), "results": []}, indent=2)

    def fetch_url(self, url: str) -> str:
        """Fetch a public URL and return title, headings, links, and bounded readable text."""
        try:
            final_url, content_type, body = self._fetch(url)
            parser = _PageParser(final_url)
            parser.feed(body)
            return json.dumps({"status": "ok", "url": final_url, "content_type": content_type, "title": " ".join(parser.title), "headings": parser.headings[:50], "links": parser.links[:100], "text": " ".join(parser.text)[: self.valves.max_text_chars]}, indent=2, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "error", "url": url, "error": str(exc)}, indent=2)

    def scrape_url_to_json(self, url: str, output_path: str, max_links: int = 50) -> str:
        """Fetch a public URL and atomically save structured JSON under the Hermes workspace."""
        result = json.loads(self.fetch_url(url))
        if result.get("status") != "ok":
            return json.dumps(result, indent=2)
        result["links"] = result.get("links", [])[: max(1, min(int(max_links), 100))]
        try:
            target = self._workspace_path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
            return json.dumps({"status": "written", "output_path": str(target.relative_to(WORKSPACE.resolve())), "title": result.get("title", ""), "heading_count": len(result.get("headings", [])), "link_count": len(result.get("links", []))}, indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "stage": "write", "error": str(exc)}, indent=2)

    def read_saved_json(self, path: str) -> str:
        """Read a saved JSON artifact from the Hermes workspace."""
        try:
            target = self._workspace_path(path)
            return target.read_text(encoding="utf-8")
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "path": path}, indent=2)

    def list_scraper_output(self) -> str:
        """List saved files under scraper/output."""
        folder = self._workspace_path("scraper/output")
        if not folder.exists():
            return json.dumps([])
        return json.dumps(sorted(str(item.relative_to(WORKSPACE.resolve())) for item in folder.rglob("*") if item.is_file()), indent=2)
