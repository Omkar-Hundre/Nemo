"""Production-grade in-depth test suite for WebResearcherTool.

Covers:
- Live web search via DuckDuckGo (title, url, snippet)
- Clean document/article extraction via Trafilatura (no HTML tags, pure markdown with metadata)
- PyPI package technical specifications & dependency lookups
- Wikipedia encyclopedic definitions and summaries
- Multi-source autonomous research synthesis
- Error boundaries (invalid URLs, missing queries, 404 packages)
"""

# 1. Standard library imports
import asyncio

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.tools.builtin import WebResearcherTool

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_web_researcher_search_duckduckgo():
    """Verify web_researcher searches live web and returns structured results."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "search", "query": "python fastapi documentation", "limit": 3}, {})
    if not res.success or res.data.get("count", 0) == 0:
        # In case of remote engine rate limiting during full suite runs, retry with simple query
        await asyncio.sleep(1.0)
        res = await tool.execute({"action": "search", "query": "fastapi", "limit": 3}, {})
    assert res.success
    data = res.data
    assert data["action"] == "search"
    assert data["count"] > 0
    first = data["results"][0]
    assert "title" in first
    assert "url" in first
    assert "snippet" in first
    assert len(first["url"]) > 0


@pytest.mark.asyncio
async def test_web_researcher_fetch_doc_markdown_clean():
    """Verify web_researcher extracts pure structured Markdown from documentation pages."""
    tool = WebResearcherTool()
    # Test on public MDN documentation page
    res = await tool.execute(
        {
            "action": "fetch_doc",
            "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Closures",
            "max_chars": 2000,
        },
        {},
    )
    assert res.success
    data = res.data
    assert data["action"] == "fetch_doc"
    assert "Closures" in data["content"] or "closure" in data["content"].lower()
    # Verify no raw HTML tag soup
    assert "<!DOCTYPE html>" not in data["content"]
    assert "<script" not in data["content"]


@pytest.mark.asyncio
async def test_web_researcher_pypi_package_lookup():
    """Verify web_researcher queries PyPI API and returns structured package metadata."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "pypi", "package_name": "pydantic"}, {})
    assert res.success
    data = res.data
    assert data["action"] == "pypi"
    assert data["name"].lower() == "pydantic"
    assert len(data["latest_version"]) > 0
    assert "data validation" in data["summary"].lower()
    assert "documentation" in data or "home_page" in data


@pytest.mark.asyncio
async def test_web_researcher_pypi_nonexistent_package():
    """Verify web_researcher reports clean error when Python package is not found on PyPI."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "pypi", "package_name": "nonexistent_pkg_random_xyz_99999"}, {})
    assert res.success is False
    assert "was not found on pypi" in res.error.lower()


@pytest.mark.asyncio
async def test_web_researcher_wiki_concept_definition():
    """Verify web_researcher queries Wikipedia REST API for clean encyclopedic summaries."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "wiki", "query": "Artificial intelligence"}, {})
    assert res.success
    data = res.data
    assert data["action"] == "wiki"
    assert "Artificial intelligence" in data["title"]
    assert len(data["summary"]) > 50
    assert "intelligence" in data["summary"].lower()
    assert "wikipedia.org" in data["url"]


@pytest.mark.asyncio
async def test_web_researcher_wiki_nonexistent_topic():
    """Verify web_researcher reports clean error for nonexistent Wikipedia topic."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "wiki", "query": "qwertyuiop_super_nonexistent_random_concept_123"}, {})
    assert res.success is False
    assert "no wikipedia article found" in res.error.lower()


@pytest.mark.asyncio
async def test_web_researcher_research_synthesis():
    """Verify web_researcher research action combines search citations with deep article text."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "research", "query": "FastAPI async python framework"}, {})
    if not res.success or res.data.get("sources_count", 0) == 0:
        await asyncio.sleep(1.0)
        res = await tool.execute({"action": "research", "query": "FastAPI", "limit": 3}, {})
    assert res.success
    data = res.data
    assert data["action"] == "research"
    assert data["sources_count"] > 0
    assert len(data["sources"]) > 0
    # Deep extracted content should be populated from top source
    assert len(data["deep_extracted_content"]) > 0


@pytest.mark.asyncio
async def test_web_researcher_missing_action_or_query():
    """Verify web_researcher validates required arguments."""
    tool = WebResearcherTool()

    # Missing query in search
    res_no_q = await tool.execute({"action": "search"}, {})
    assert res_no_q.success is False
    assert "query parameter is required" in res_no_q.error.lower()

    # Missing url in fetch_doc
    res_no_url = await tool.execute({"action": "fetch_doc"}, {})
    assert res_no_url.success is False
    assert "url parameter is required" in res_no_url.error.lower()

    # Unsupported action
    res_invalid = await tool.execute({"action": "magic_action"}, {})
    assert res_invalid.success is False
    assert "unsupported research action" in res_invalid.error.lower()


@pytest.mark.asyncio
async def test_web_researcher_fetch_doc_invalid_url():
    """Verify web_researcher gracefully handles unreachable or invalid URLs."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "fetch_doc", "url": "https://unreachable-domain-123456789.com/doc"}, {})
    assert res.success is False
    assert "failed to fetch content" in res.error.lower() or "document extraction failed" in res.error.lower()


# 6. Public exports
__all__ = [
    "test_web_researcher_search_duckduckgo",
    "test_web_researcher_fetch_doc_markdown_clean",
    "test_web_researcher_pypi_package_lookup",
    "test_web_researcher_pypi_nonexistent_package",
    "test_web_researcher_wiki_concept_definition",
    "test_web_researcher_wiki_nonexistent_topic",
    "test_web_researcher_research_synthesis",
    "test_web_researcher_missing_action_or_query",
    "test_web_researcher_fetch_doc_invalid_url",
]
