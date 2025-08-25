"""
Web Search tools
"""
from langchain_core.tools import tool

import asyncio
import threading
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


#############################
# Internal async primitives #
#############################

def _run_async(coro):
    """Run an async coroutine from sync context safely (supports nested event loops)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no running loop
        return asyncio.run(coro)
    else:
        # Run in separate thread with dedicated loop to avoid nesting issues
        container = {}
        def runner():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                container["result"] = new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join()
        return container.get("result")


async def _ddg_html_search_async(query: str, max_results: int = 10, country: str = "us-en", site: Optional[str] = None) -> List[dict]:
    searcher = Searcher()
    if site:
        query = f"{query} site:{site}"
    try:
        results = await searcher.search_duckduckgo(query, max_results=max_results, country=country)
    except Exception:
        return []
    return [asdict(r) for r in results]


async def _ddg_html_search_enrich_async(
    query: str,
    max_results: int = 10,
    country: str = "us-en",
    enrich_limit: int = 5,
    site: Optional[str] = None,
) -> List[dict]:
    searcher = Searcher()
    if site:
        query = f"{query} site:{site}"
    try:
        results = await searcher.search_duckduckgo(query, max_results=max_results, country=country)
        results = await searcher.enrich_with_meta(results, limit=enrich_limit)
    except Exception:
        return []
    return [asdict(r) for r in results]


async def _visit_website_async(url: str, max_chars: int = 8000, timeout_sec: int = 20) -> dict:
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


async def _visit_many_async(urls: List[str], max_chars: int = 8000, timeout_sec: int = 20, concurrency: int = 10) -> List[dict]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    timeout = ClientTimeout(total=timeout_sec)

    async def one(u: str):
        async with sem:
            return await _visit_website_async(u, max_chars=max_chars, timeout_sec=timeout_sec)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:  # session reused by delegated call? _visit_website_async creates its own
        # For simplicity we just call separate; optimization: refactor to pass session.
        tasks = [one(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[dict] = []
    for r in results:
        if isinstance(r, dict):
            out.append(r)
        else:  # exception
            out.append({"ok": False, "error": str(r)})
    return out


async def _crawl_website_async(
    start_url: str,
    max_pages: int = 5,
    same_domain: bool = True,
    max_depth: int = 2,
    max_chars: int = 2000,
    timeout_sec: int = 20,
) -> List[dict]:
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

#############################
# Public sync tool wrappers #
#############################

@tool("ddg_html_search")
def ddg_html_search(query: str, max_results: int = 10, country: str = "us-en", site: Optional[str] = None) -> List[dict]:
    """DuckDuckGo HTML search (no-JS). Synchronous wrapper returning list of results."""
    return _run_async(_ddg_html_search_async(query=query, max_results=max_results, country=country, site=site))


@tool("ddg_html_search_enrich")
def ddg_html_search_enrich(
    query: str,
    max_results: int = 10,
    country: str = "us-en",
    enrich_limit: int = 5,
    site: Optional[str] = None,
) -> List[dict]:
    """DuckDuckGo HTML search + metadata enrichment. Synchronous wrapper."""
    return _run_async(_ddg_html_search_enrich_async(query=query, max_results=max_results, country=country, enrich_limit=enrich_limit, site=site))


@tool("visit_website")
def visit_website(url: str, max_chars: int = 8000, timeout_sec: int = 20) -> dict:
    """Visit a website and extract title, description, truncated text, and links. Synchronous wrapper."""
    return _run_async(_visit_website_async(url=url, max_chars=max_chars, timeout_sec=timeout_sec))


@tool("visit_websites_batch")
def visit_websites_batch(urls: List[str], max_chars: int = 8000, timeout_sec: int = 20, concurrency: int = 10) -> List[dict]:
    """Visit multiple websites concurrently (async under the hood) and return list of per-site results.

    Inputs:
    - urls: list of absolute URLs
    - max_chars: truncate each page's text
    - timeout_sec: per-request timeout
    - concurrency: max simultaneous fetches
    """
    return _run_async(_visit_many_async(urls=urls, max_chars=max_chars, timeout_sec=timeout_sec, concurrency=concurrency))


@tool("crawl_website")
def crawl_website(
    start_url: str,
    max_pages: int = 5,
    same_domain: bool = True,
    max_depth: int = 2,
    max_chars: int = 2000,
    timeout_sec: int = 20,
) -> List[dict]:
    """Crawl a website (BFS) collecting small summaries. Synchronous wrapper over async crawler."""
    return _run_async(_crawl_website_async(start_url=start_url, max_pages=max_pages, same_domain=same_domain, max_depth=max_depth, max_chars=max_chars, timeout_sec=timeout_sec))
