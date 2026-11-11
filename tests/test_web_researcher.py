"""Production-grade in-depth test suite for WebResearcherTool.

Covers:
- Tool definition and parameter schemas
- Live web search via DuckDuckGo (title, url, snippet)
- Search result limits and bounds enforcement
- Clean document/article extraction via Trafilatura (no HTML tags, pure markdown with metadata)
- Max chars truncation on document extraction
- Graceful error boundaries on unreachable/invalid URLs
- PyPI package technical specifications & dependency lookups
- PyPI 404 package handling and missing argument validation
- Wikipedia encyclopedic definitions, summaries, and desktop URLs
- Wikipedia 404 topic handling and missing argument validation
- Multi-source autonomous research synthesis
- Input argument boundaries and unsupported action handling
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
def test_web_researcher_definition():
    """Verify web_researcher tool metadata, schema, and allowed actions."""
    tool = WebResearcherTool()
    defn = tool.get_definition()
    assert defn.name == "web_researcher"
    assert "search" in defn.description.lower()
    props = defn.parameters["properties"]
    assert "action" in props
    assert "query" in props
    assert "url" in props
    assert "package_name" in props
    assert "limit" in props
    assert "max_chars" in props
    allowed_actions = props["action"]["enum"]
    assert "search" in allowed_actions
    assert "fetch_doc" in allowed_actions
    assert "pypi" in allowed_actions
    assert "wiki" in allowed_actions
    assert "research" in allowed_actions


@pytest.mark.asyncio
async def test_web_researcher_search_duckduckgo():
    """Verify web_researcher searches live web and returns structured results."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "search", "query": "python fastapi documentation", "limit": 3}, {})
    if not res.success or res.data.get("count", 0) == 0:
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
async def test_web_researcher_search_custom_limit():
    """Verify web_researcher respects custom limit parameter."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "search", "query": "python", "limit": 2}, {})
    assert res.success
    data = res.data
    assert data["count"] <= 2
    assert len(data["results"]) <= 2


@pytest.mark.asyncio
async def test_web_researcher_fetch_doc_markdown_clean():
    """Verify web_researcher extracts pure structured Markdown from documentation pages."""
    tool = WebResearcherTool()
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
async def test_web_researcher_fetch_doc_max_chars():
    """Verify web_researcher truncates extracted documentation to max_chars."""
    tool = WebResearcherTool()
    res = await tool.execute(
        {
            "action": "fetch_doc",
            "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Closures",
            "max_chars": 350,
        },
        {},
    )
    assert res.success
    assert len(res.data["content"]) <= 350


@pytest.mark.asyncio
async def test_web_researcher_fetch_doc_invalid_url():
    """Verify web_researcher gracefully handles unreachable or invalid URLs."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "fetch_doc", "url": "https://unreachable-domain-xyz-987654321.com/doc"}, {})
    assert res.success is False
    assert "failed to fetch content" in res.error.lower() or "document extraction failed" in res.error.lower()


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
async def test_web_researcher_pypi_query_fallback():
    """Verify web_researcher accepts query argument as package_name fallback."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "pypi", "query": "httpx"}, {})
    assert res.success
    data = res.data
    assert data["name"].lower() == "httpx"
    assert len(data["latest_version"]) > 0


@pytest.mark.asyncio
async def test_web_researcher_pypi_nonexistent_package():
    """Verify web_researcher reports clean error when Python package is not found on PyPI."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "pypi", "package_name": "nonexistent_pkg_random_xyz_99999"}, {})
    assert res.success is False
    assert "was not found on pypi" in res.error.lower()


@pytest.mark.asyncio
async def test_web_researcher_pypi_missing_param():
    """Verify web_researcher requires package_name for pypi action."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "pypi"}, {})
    assert res.success is False
    assert "package_name is required" in res.error.lower()


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
async def test_web_researcher_wiki_missing_query():
    """Verify web_researcher requires query for wiki action."""
    tool = WebResearcherTool()
    res = await tool.execute({"action": "wiki"}, {})
    assert res.success is False
    assert "query parameter is required" in res.error.lower()


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

    # Missing query in research
    res_no_res_q = await tool.execute({"action": "research"}, {})
    assert res_no_res_q.success is False
    assert "query parameter is required" in res_no_res_q.error.lower()

    # Unsupported action
    res_invalid = await tool.execute({"action": "magic_action"}, {})
    assert res_invalid.success is False
    assert "unsupported research action" in res_invalid.error.lower()
