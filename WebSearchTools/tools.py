"""
Web Search tools
"""
from langchain_core.tools import tool

import asyncio
from dataclasses import dataclass, asdict
from typing import List, Optional, Set, Tuple
import re
import aiohttp
from aiohttp import ClientTimeout
from bs4 import BeautifulSoup
from yarl import URL

DUCKDUCKGO_HTML = "https://duckduckgo.com/html/"  # no-JS results page

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36"
)


@dataclass
class SearchResult:
    rank: int
    title: str
    url: str
    snippet: str
    meta_description: Optional[str] = None


class Searcher:
    def __init__(
        self,
        *,
        timeout_sec: int = 15,
        concurrency: int = 8,
        verify_ssl: bool = True,
    ):
        self.timeout = ClientTimeout(total=timeout_sec)
        self.sem = asyncio.Semaphore(concurrency)
        self.verify_ssl = verify_ssl

    async def _fetch(self, session: aiohttp.ClientSession, url: str, **kwargs) -> str:
        async with self.sem:
            async with session.get(
                url, timeout=self.timeout, ssl=self.verify_ssl, **kwargs
            ) as resp:
                resp.raise_for_status()
                return await resp.text()

    async def search_duckduckgo(
        self, query: str, max_results: int = 10, *, country: str = "us-en"
    ) -> List[SearchResult]:
        """
        Perform a search on DuckDuckGo HTML results (no-JS).
        """
        params = {
            "q": query,
            "kl": country,  # region/lang
        }
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

        async with aiohttp.ClientSession(headers=headers) as session:
            html = await self._fetch(session, DUCKDUCKGO_HTML, params=params)
            results = self._parse_duckduckgo_results(html)
            return results[:max_results]

    def _parse_duckduckgo_results(self, html: str) -> List[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[SearchResult] = []

        # DuckDuckGo HTML layout: results in <div class="result"> with <a class="result__a">
        for i, res in enumerate(soup.select("div.result"), start=1):
            a = res.select_one("a.result__a")
            if not a:
                continue
            raw_title = a.get_text() or ""
            title = re.sub(r"\s+", " ", raw_title).strip()
            # The link is direct in HTML version
            href = a.get("href")
            url = self._clean_url(href)

            # snippet
            snippet_el = res.select_one("a.result__snippet") or res.select_one("div.result__snippet")
            raw_snippet = snippet_el.get_text() if snippet_el else ""
            snippet = re.sub(r"\s+", " ", raw_snippet).strip()

            out.append(SearchResult(rank=i, title=title, url=url, snippet=snippet))
        return out

    def _clean_url(self, href: Optional[str]) -> str:
        if not href:
            return ""
        # Normalize relative or redirect links
        try:
            u = URL(href)
            return str(u)
        except Exception:
            return href

    async def enrich_with_meta(
        self, results: List[SearchResult], *, limit: int = 5
    ) -> List[SearchResult]:
        """
        Concurrently fetch page HTML for top N results and extract meta description/title as better snippet.
        """
        to_fetch = results[:limit]
        async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
            tasks = [self._get_meta(session, r) for r in to_fetch]
            metas = await asyncio.gather(*tasks, return_exceptions=True)

        for r, meta in zip(to_fetch, metas):
            if isinstance(meta, dict):
                r.meta_description = meta.get("description") or r.snippet
                # Prefer page <title> if it looks useful
                if meta.get("title") and len(meta["title"]) > 3:
                    r.title = meta["title"]
        return results

    async def _get_meta(self, session: aiohttp.ClientSession, r: SearchResult) -> dict:
        try:
            html = await self._fetch(session, r.url)
        except Exception:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        raw_title = soup.title.get_text() if soup.title else ""
        title = re.sub(r"\s+", " ", raw_title).strip()[:300]

        # Try common meta description patterns
        desc = ""
        for sel in [
            'meta[name="description"]',
            'meta[name="Description"]',
            'meta[property="og:description"]',
            'meta[name="twitter:description"]',
        ]:
            el = soup.select_one(sel)
            if el and el.get("content"):
                desc = el.get("content").strip()
                break

        # Fallback: grab first <p> as a crude summary
        if not desc:
            p = soup.find("p")
            if p:
                desc = re.sub(r"\s+", " ", p.get_text(strip=True))
        return {"title": title, "description": desc[:500]}

    # --- helpers for page extraction ---
    @staticmethod
    def _extract_text_and_links(html: str, base_url: Optional[str] = None, max_links: int = 100) -> Tuple[str, List[str]]:
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        raw_text = soup.get_text() or ""
        text = re.sub(r"\s+", " ", raw_text).strip()
        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href = (a["href"] or "").strip()
            try:
                u = URL(href)
                if not u.is_absolute() and base_url:
                    u = URL(base_url).join(URL(href))
                if u.scheme in ("http", "https"):
                    links.append(str(u))
            except Exception:
                continue
            if len(links) >= max_links:
                break
        return text, links


# Tools

@tool("ddg_html_search")
async def ddg_html_search(query: str, max_results: int = 10, country: str = "us-en", site: Optional[str] = None) -> List[dict]:
    """DuckDuckGo HTML search (no-JS). Return a list of results with rank, title, url, snippet.

    Inputs:
    - query: search keywords
    - max_results: max number of results to return (default 10)
    - country: region/language code for DuckDuckGo (e.g., 'us-en')
    - site: optional site filter, e.g., 'example.com' (will be applied as 'site:example.com')
    """
    searcher = Searcher()
    if site:
        # Append site filter safely
        query = f"{query} site:{site}"
    try:
        results = await searcher.search_duckduckgo(query, max_results=max_results, country=country)
    except Exception:
        return []
    return [asdict(r) for r in results]


@tool("ddg_html_search_enrich")
async def ddg_html_search_enrich(
    query: str,
    max_results: int = 10,
    country: str = "us-en",
    enrich_limit: int = 5,
    site: Optional[str] = None,
) -> List[dict]:
    """DuckDuckGo HTML search and enrich top results by fetching page metadata.

    Returns a list of results with rank, title, url, snippet, meta_description.

    Inputs:
    - query: search keywords
    - max_results: max number of results to return (default 10)
    - country: region/language code for DuckDuckGo (e.g., 'us-en')
    - enrich_limit: number of top results to fetch for metadata (default 5)
    - site: optional site filter, e.g., 'example.com' (will be applied as 'site:example.com')
    """
    searcher = Searcher()
    if site:
        query = f"{query} site:{site}"
    try:
        results = await searcher.search_duckduckgo(query, max_results=max_results, country=country)
        results = await searcher.enrich_with_meta(results, limit=enrich_limit)
    except Exception:
        return []
    return [asdict(r) for r in results]


@tool("visit_website")
async def visit_website(url: str, max_chars: int = 8000, timeout_sec: int = 20) -> dict:
    """Visit a website URL and extract title, meta description, text content, and links.

    Inputs:
    - url: absolute URL to visit
    - max_chars: truncate extracted text to this many characters (default 8000)
    - timeout_sec: request timeout seconds (default 20)
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    timeout = ClientTimeout(total=timeout_sec)
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                status = resp.status
                final_url = str(resp.url)
                html = await resp.text()
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}

    soup = BeautifulSoup(html, "html.parser")
    raw_title = soup.title.get_text() if soup.title else ""
    title = re.sub(r"\s+", " ", raw_title).strip()
    desc = ""
    for sel in [
        'meta[name="description"]',
        'meta[name="Description"]',
        'meta[property="og:description"]',
        'meta[name="twitter:description"]',
    ]:
        el = soup.select_one(sel)
        if el and el.get("content"):
            desc = el.get("content").strip()
            break
    text, links = Searcher._extract_text_and_links(html, base_url=final_url, max_links=100)
    return {
        "ok": True,
        "status": status,
        "url": url,
        "final_url": final_url,
        "title": title,
        "description": desc[:500],
        "text": text[:max_chars],
        "links": links,
    }


@tool("crawl_website")
async def crawl_website(
    start_url: str,
    max_pages: int = 5,
    same_domain: bool = True,
    max_depth: int = 2,
    max_chars: int = 2000,
    timeout_sec: int = 20,
) -> List[dict]:
    """Crawl a website starting from a URL (small BFS), extracting summary per page.

    Inputs:
    - start_url: starting absolute URL
    - max_pages: maximum pages to fetch (default 5)
    - same_domain: stay within the start domain only (default True)
    - max_depth: maximum link depth (default 2)
    - max_chars: truncate each page's text to this length (default 2000)
    - timeout_sec: request timeout seconds (default 20)
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    timeout = ClientTimeout(total=timeout_sec)
    start = URL(start_url)
    start_host = start.host
    visited: Set[str] = set()
    queue: List[Tuple[str, int]] = [(str(start), 0)]
    out: List[dict] = []

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        while queue and len(out) < max_pages:
            url, depth = queue.pop(0)
            if url in visited or depth > max_depth:
                continue
            visited.add(url)
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    html = await resp.text()
                    final_url = str(resp.url)
                    status = resp.status
            except Exception:
                continue

            soup = BeautifulSoup(html, "html.parser")
            raw_title = soup.title.get_text() if soup.title else ""
            title = re.sub(r"\s+", " ", raw_title).strip()
            text, links = Searcher._extract_text_and_links(html, base_url=final_url, max_links=50)
            out.append({
                "url": url,
                "final_url": final_url,
                "status": status,
                "title": title,
                "text": text[:max_chars],
            })

            # Enqueue next links
            for link in links:
                try:
                    u = URL(link)
                except Exception:
                    continue
                if same_domain and u.host != start_host:
                    continue
                if link not in visited and len(queue) + len(out) < max_pages * 3:
                    queue.append((link, depth + 1))

    return out
