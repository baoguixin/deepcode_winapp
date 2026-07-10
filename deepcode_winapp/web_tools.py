from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .diagnostics import append_diagnostic


class WebToolError(RuntimeError):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str = ""


@dataclass(frozen=True)
class SearchEngine:
    name: str
    build_url: Callable[[str, str], str]
    parser: Callable[[str], list[SearchResult]]


def web_search(query: str, max_results: int = 5, region: str = "cn-zh") -> str:
    cleaned_query = query.strip()
    if not cleaned_query:
        raise WebToolError("Search query is required.")
    limit = max(1, min(int(max_results), 10))
    results: list[SearchResult] = []
    status: list[str] = []

    for engine in search_engines_for_query(cleaned_query):
        if len(results) >= limit:
            break
        url = engine.build_url(cleaned_query, region or "cn-zh")
        append_diagnostic(f"WEB_SEARCH engine={engine.name} query={cleaned_query!r} url={url}")
        try:
            body = _fetch_text(url, timeout=20, max_bytes=1_500_000)
            parsed = engine.parser(body)
            parsed = [SearchResult(item.title, item.url, item.snippet, item.engine or engine.name) for item in parsed]
            if parsed:
                status.append(f"{engine.name}: {len(parsed)} results")
                results.extend(parsed)
            else:
                status.append(f"{engine.name}: no parsable results")
        except Exception as exc:
            status.append(f"{engine.name}: {type(exc).__name__}: {exc}")
            append_diagnostic(f"WEB_SEARCH engine={engine.name} failed: {type(exc).__name__}: {exc}")

    results = _dedupe_results(results)[:limit]
    if not results:
        raise WebToolError("No web search results available. Engine status: " + " | ".join(status))
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        engine = f" [{result.engine}]" if result.engine else ""
        lines.append(f"{index}. {result.title}{engine}\n   URL: {result.url}\n   Snippet: {result.snippet}")
    if status:
        lines.append("\nEngine status: " + " | ".join(status))
    return "\n".join(lines)


def web_fetch(url: str, max_chars: int = 12000) -> str:
    cleaned_url = url.strip()
    if not cleaned_url.startswith(("http://", "https://")):
        raise WebToolError("Only http:// and https:// URLs are supported.")
    append_diagnostic(f"WEB_FETCH url={cleaned_url}")
    body = _fetch_text(cleaned_url, timeout=30, max_bytes=2_000_000)
    text = html_to_text(body)
    limit = max(1000, min(int(max_chars), 50000))
    if len(text) > limit:
        return text[:limit] + f"\n[truncated: {len(text) - limit} chars omitted]"
    return text


def parse_duckduckgo_html(body: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    blocks = re.findall(r'<div[^>]+class="[^"]*\bresult\b[^"]*".*?</div>\s*</div>', body, flags=re.I | re.S)
    if not blocks:
        blocks = re.findall(r'<a[^>]+class="result__a".*?</a>.*?(?=<a[^>]+class="result__a"|$)', body, flags=re.I | re.S)
    for block in blocks:
        title_match = re.search(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
        if not title_match:
            continue
        raw_url = html.unescape(title_match.group(1))
        title = html_to_text(title_match.group(2))
        result_url = normalize_duckduckgo_url(raw_url)
        snippet_match = re.search(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
        if not snippet_match:
            snippet_match = re.search(r'<div[^>]+class="result__snippet"[^>]*>(.*?)</div>', block, flags=re.I | re.S)
        snippet = html_to_text(snippet_match.group(1)) if snippet_match else ""
        if title and result_url:
            results.append(SearchResult(title=title, url=result_url, snippet=snippet, engine="DuckDuckGo"))
    return _dedupe_results(results)


def parse_duckduckgo_lite_html(body: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.I | re.S):
        raw_url = html.unescape(match.group(1))
        title = html_to_text(match.group(2))
        url = normalize_duckduckgo_url(raw_url)
        if not _is_search_result_url(url) or not title or title.lower() in {"next page", "previous page"}:
            continue
        window = body[match.end() : match.end() + 800]
        snippet = html_to_text(window.split("</tr>", 1)[0])
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="DuckDuckGo Lite"))
    return _dedupe_results(results)


def parse_bing_html(body: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    blocks = re.findall(r'<li[^>]+class="b_algo"[^>]*>.*?</li>', body, flags=re.I | re.S)
    for block in blocks:
        title_match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>', block, flags=re.I | re.S)
        if not title_match:
            continue
        url = html.unescape(title_match.group(1))
        title = html_to_text(title_match.group(2))
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.I | re.S)
        snippet = html_to_text(snippet_match.group(1)) if snippet_match else ""
        if _is_search_result_url(url) and title:
            results.append(SearchResult(title=title, url=url, snippet=snippet, engine="Bing"))
    return _dedupe_results(results)


def parse_baidu_html(body: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    blocks = re.findall(r'<div[^>]+class="[^"]*(?:result|c-container)[^"]*"[^>]*>.*?(?=<div[^>]+class="[^"]*(?:result|c-container)|$)', body, flags=re.I | re.S)
    for block in blocks:
        title_match = re.search(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>', block, flags=re.I | re.S)
        if not title_match:
            continue
        mu_match = re.search(r'\bmu="([^"]+)"', block, flags=re.I)
        url = html.unescape(mu_match.group(1) if mu_match else title_match.group(1))
        title = html_to_text(title_match.group(2))
        snippet = html_to_text(re.sub(r"(?is)<h3.*?</h3>", " ", block))[:300]
        if _is_search_result_url(url) and title:
            results.append(SearchResult(title=title, url=url, snippet=snippet, engine="Baidu"))
    return _dedupe_results(results)


def parse_sogou_weixin_html(body: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    blocks = re.findall(r'<li[^>]*>.*?</li>', body, flags=re.I | re.S)
    for block in blocks:
        title_match = re.search(r'<h[34][^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h[34]>', block, flags=re.I | re.S)
        if not title_match:
            title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*(?:txt|news|title)[^"]*"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
        if not title_match:
            continue
        url = html.unescape(title_match.group(1))
        title = html_to_text(title_match.group(2))
        snippet_match = re.search(r'<p[^>]+class="[^"]*(?:txt-info|summary|desc)[^"]*"[^>]*>(.*?)</p>', block, flags=re.I | re.S)
        snippet = html_to_text(snippet_match.group(1)) if snippet_match else html_to_text(block)[:300]
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://weixin.sogou.com" + url
        if _is_search_result_url(url) and title:
            results.append(SearchResult(title=title, url=url, snippet=snippet, engine="Sogou Weixin"))
    return _dedupe_results(results)


def normalize_duckduckgo_url(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return urllib.parse.unquote(query["uddg"][0])
    if raw_url.startswith("//"):
        return "https:" + raw_url
    if raw_url.startswith("/"):
        return "https://duckduckgo.com" + raw_url
    return raw_url


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _fetch_text(url: str, timeout: int, max_bytes: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DeepCodeWinApp/0.2",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(max_bytes + 1)
    except Exception as exc:
        raise WebToolError(f"Network request failed: {exc}") from exc
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode(charset, errors="replace")


def search_engines_for_query(query: str) -> list[SearchEngine]:
    engines = [
        SearchEngine("DuckDuckGo HTML", _duckduckgo_html_url, parse_duckduckgo_html),
        SearchEngine("DuckDuckGo Lite", _duckduckgo_lite_url, parse_duckduckgo_lite_html),
        SearchEngine("Bing", _bing_url, parse_bing_html),
        SearchEngine("Baidu", _baidu_url, parse_baidu_html),
    ]
    if any(term in query for term in ("公众号", "微信", "爆款", "选题", "小红书", "热点")):
        engines.insert(0, SearchEngine("Sogou Weixin", _sogou_weixin_url, parse_sogou_weixin_html))
    return engines


def _duckduckgo_html_url(query: str, region: str) -> str:
    return "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": region})


def _duckduckgo_lite_url(query: str, region: str) -> str:
    return "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query, "kl": region})


def _bing_url(query: str, _region: str) -> str:
    return "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "setlang": "zh-CN"})


def _baidu_url(query: str, _region: str) -> str:
    return "https://www.baidu.com/s?" + urllib.parse.urlencode({"wd": query})


def _sogou_weixin_url(query: str, _region: str) -> str:
    return "https://weixin.sogou.com/weixin?" + urllib.parse.urlencode({"type": "2", "query": query})


def _is_search_result_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    blocked_hosts = ("duckduckgo.com/y.js", "duckduckgo.com/html", "duckduckgo.com/lite")
    return not any(host in url for host in blocked_hosts)


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        key = result.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped
