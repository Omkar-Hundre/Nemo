"""Comprehensive in-depth test suite for document generation, reading, edge cases, and security."""

# 1. Standard library imports
import csv
import io
from pathlib import Path
import tempfile

# 2. Third-party imports
import docx
import pypdf
import pytest

# 3. Local / internal imports
from nemo.security.policy import SecurityPolicy
from nemo.tools.builtin import DocumentGeneratorTool, DocumentReaderTool

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
MINIMAL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_docx_multilevel_headings_and_structure():
    """Verify DOCX generation and reading with Title, Heading 1, 2, and body paragraphs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        reader = DocumentReaderTool()
        doc_path = root / "multilevel_doc.docx"

        res_gen = await gen.execute(
            {
                "path": str(doc_path),
                "title": "System Architecture Specification",
                "format": "docx",
                "sections": [
                    {
                        "heading": "1. High-Level Architecture",
                        "level": 1,
                        "body": "NEMO orchestrates native tasks directly on Windows.",
                        "bullets": ["Low latency", "Isolated processes"],
                    },
                    {
                        "heading": "1.1 Subprocess Controller",
                        "level": 2,
                        "body": "Processes execute asynchronously with stream redirection.",
                    },
                    {
                        "heading": "2. Memory Persistence Engine",
                        "level": 1,
                        "body": "SQLite-backed relational repository.",
                    },
                ],
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success
        assert doc_path.exists()

        res_read = await reader.execute({"path": str(doc_path)}, {"working_directory": str(root)})
        assert res_read.success
        data = res_read.data
        assert data["format"] == "docx"
        assert data["heading_count"] == 4  # Title (Heading 0 or Title) + 3 sections
        headings = [h["text"] for h in data["headings"]]
        assert "System Architecture Specification" in headings
        assert "1. High-Level Architecture" in headings
        assert "1.1 Subprocess Controller" in headings
        assert "2. Memory Persistence Engine" in headings
        assert data["word_count"] > 10


@pytest.mark.asyncio
async def test_docx_rich_tables_with_headers_and_empty_cells():
    """Verify DOCX table formatting with bold headers, multi-columns, and empty/unicode cells."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        reader = DocumentReaderTool()
        doc_path = root / "report_with_tables.docx"

        table_headers = ["Service", "Port", "Status", "Notes"]
        table_rows = [
            ["FastAPI Gateway", "8000", "ACTIVE", "Public ingress"],
            ["SQLite Database", "", "LOCAL", "Persistent volume"],
            ["NVIDIA NIM 120B", "11434", "CONNECTED", "Super VL 🚀 & <XML>"],
        ]

        res_gen = await gen.execute(
            {
                "path": str(doc_path),
                "title": "Service Inventory Report",
                "format": "docx",
                "sections": [
                    {
                        "heading": "Service Grid",
                        "body": "Below is the current state of active services:",
                        "table": {
                            "headers": table_headers,
                            "rows": table_rows,
                        },
                    }
                ],
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success

        res_read = await reader.execute({"path": str(doc_path)}, {"working_directory": str(root)})
        assert res_read.success
        tables = res_read.data["tables"]
        assert len(tables) == 1
        parsed_table = tables[0]
        assert parsed_table["headers"] == table_headers
        assert len(parsed_table["rows"]) == 3
        assert parsed_table["rows"][0] == ["FastAPI Gateway", "8000", "ACTIVE", "Public ingress"]
        assert parsed_table["rows"][1][1] == ""  # Empty port cell preserved
        assert "Super VL 🚀 & <XML>" in parsed_table["rows"][2][3]


@pytest.mark.asyncio
async def test_docx_embedded_images_and_captions():
    """Verify embedding native PNG images into DOCX with centered captions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        img_path = root / "arch_diagram.png"
        img_path.write_bytes(MINIMAL_PNG_BYTES)

        gen = DocumentGeneratorTool()
        reader = DocumentReaderTool()
        doc_path = root / "visual_report.docx"

        res_gen = await gen.execute(
            {
                "path": str(doc_path),
                "title": "Visual Topology",
                "format": "docx",
                "sections": [
                    {
                        "heading": "System Diagram",
                        "body": "Figure 1 illustrates the architecture pipeline:",
                        "image_path": "arch_diagram.png",
                        "caption": "Figure 1: Architectural Dataflow Overview",
                        "width_inches": 4.5,
                    }
                ],
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success

        res_read = await reader.execute({"path": str(doc_path)}, {"working_directory": str(root)})
        assert res_read.success
        assert res_read.data["image_count"] == 1
        assert "Figure 1: Architectural Dataflow Overview" in res_read.data["content"]


@pytest.mark.asyncio
async def test_docx_code_blocks_and_styled_callouts():
    """Verify DOCX generation and reading of Consolas code blocks and styled callout notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        reader = DocumentReaderTool()
        doc_path = root / "code_spec.docx"

        code_snippet = "def execute_task(cmd: str) -> bool:\n    return True"
        callout_text = "Ensure all sensitive tokens are excluded from logs."

        res_gen = await gen.execute(
            {
                "path": str(doc_path),
                "title": "Developer Guidelines",
                "format": "docx",
                "sections": [
                    {
                        "heading": "Implementation Standard",
                        "code": code_snippet,
                        "callout": callout_text,
                    }
                ],
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success

        res_read = await reader.execute({"path": str(doc_path)}, {"working_directory": str(root)})
        assert res_read.success
        assert "def execute_task(cmd: str)" in res_read.data["content"]
        assert "NOTE: Ensure all sensitive tokens are excluded from logs." in res_read.data["content"]


@pytest.mark.asyncio
async def test_docx_metadata_author_and_title_roundtrip():
    """Verify author and title core properties are preserved in DOCX package metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        reader = DocumentReaderTool()
        doc_path = root / "metadata_test.docx"

        res_gen = await gen.execute(
            {
                "path": str(doc_path),
                "title": "Formal Security Audit",
                "author": "NEMO Deep Senior Dev",
                "format": "docx",
                "sections": [
                    {"heading": "Audit Summary", "body": "All automated gates passed cleanly."}
                ],
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success

        res_read = await reader.execute({"path": str(doc_path)}, {"working_directory": str(root)})
        assert res_read.success
        meta = res_read.data["metadata"]
        assert meta["title"] == "Formal Security Audit"
        assert meta["author"] == "NEMO Deep Senior Dev"
        assert meta["created"] != ""


@pytest.mark.asyncio
async def test_docx_raw_markdown_content_fallback():
    """Verify DOCX generation from raw markdown syntax (# heading, ## heading, bullet points)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        reader = DocumentReaderTool()
        doc_path = root / "raw_md_doc.docx"

        raw_md = (
            "# Primary Objective\n\n"
            "Accelerate native Windows dev tooling without bloat.\n\n"
            "## Requirements\n\n"
            "- Sub-10ms process invocation\n"
            "- Zero memory leaks\n"
            "- Robust document extraction\n"
        )

        res_gen = await gen.execute(
            {
                "path": str(doc_path),
                "title": "Fallback Markdown Parsing",
                "format": "docx",
                "content": raw_md,
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success

        res_read = await reader.execute({"path": str(doc_path)}, {"working_directory": str(root)})
        assert res_read.success
        assert "Primary Objective" in res_read.data["content"]
        assert "Requirements" in res_read.data["content"]
        assert "Sub-10ms process invocation" in res_read.data["content"]


@pytest.mark.asyncio
async def test_pdf_multipage_generation_and_page_limiting():
    """Verify reading multi-page PDF with max_pages limits and page count metrics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pdf_path = root / "multipage_doc.pdf"

        # Generate a 4-page PDF with pypdf
        writer = pypdf.PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=300, height=300)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        reader = DocumentReaderTool()
        # Limit extraction to 2 pages
        res = await reader.execute(
            {"path": str(pdf_path), "max_pages": 2},
            {"working_directory": str(root)},
        )
        assert res.success
        assert res.data["format"] == "pdf"
        assert res.data["total_pages"] == 4
        assert res.data["pages_extracted"] == 2
        assert "--- Page 1 ---" in res.data["content"]
        assert "--- Page 2 ---" in res.data["content"]
        assert "--- Page 3 ---" not in res.data["content"]


@pytest.mark.asyncio
async def test_pdf_metadata_extraction_and_encryption_check():
    """Verify PDF reader extracts metadata dictionary and validates encryption flag."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pdf_path = root / "metadata_doc.pdf"

        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_metadata({
            "/Title": "NEMO Technical Whitepaper",
            "/Author": "Omkar",
            "/Subject": "AI Systems",
        })
        with open(pdf_path, "wb") as f:
            writer.write(f)

        reader = DocumentReaderTool()
        res = await reader.execute({"path": str(pdf_path)}, {"working_directory": str(root)})
        assert res.success
        assert res.data["is_encrypted"] is False
        meta = res.data["metadata"]
        assert meta.get("title") == "NEMO Technical Whitepaper"
        assert meta.get("author") == "Omkar"


@pytest.mark.asyncio
async def test_pdf_corrupt_file_graceful_handling():
    """Verify DocumentReaderTool gracefully handles 0-byte or corrupted PDF files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        corrupt_pdf = root / "corrupt.pdf"
        corrupt_pdf.write_bytes(b"%PDF-1.4 [corrupted EOF")

        reader = DocumentReaderTool()
        res = await reader.execute({"path": str(corrupt_pdf)}, {"working_directory": str(root)})
        assert res.success is False
        assert "failed to read document" in res.error.lower()


@pytest.mark.asyncio
async def test_csv_auto_sniffer_delimiters():
    """Verify DocumentReaderTool auto-detects comma, semicolon, tab, and pipe delimiters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        reader = DocumentReaderTool()

        # 1. Semicolon delimited
        semi_csv = root / "semi.csv"
        semi_csv.write_text("item;qty;price\nWidget A;10;49.99\nWidget B;5;19.99\n", encoding="utf-8")
        res_semi = await reader.execute({"path": str(semi_csv)}, {"working_directory": str(root)})
        assert res_semi.success
        assert res_semi.data["delimiter"] == ";"
        assert res_semi.data["headers"] == ["item", "qty", "price"]
        assert len(res_semi.data["rows"]) == 3

        # 2. Pipe delimited
        pipe_csv = root / "pipe.csv"
        pipe_csv.write_text("id|name|level\n1|Alice|Admin\n2|Bob|User\n", encoding="utf-8")
        res_pipe = await reader.execute({"path": str(pipe_csv)}, {"working_directory": str(root)})
        assert res_pipe.success
        assert res_pipe.data["delimiter"] == "|"
        assert res_pipe.data["headers"] == ["id", "name", "level"]
        assert len(res_pipe.data["rows"]) == 3

        # 3. TSV (tab delimited)
        tsv_file = root / "data.tsv"
        tsv_file.write_text("colA\tcolB\n100\t200\n", encoding="utf-8")
        res_tsv = await reader.execute({"path": str(tsv_file)}, {"working_directory": str(root)})
        assert res_tsv.success
        assert res_tsv.data["delimiter"] == "\t"
        assert res_tsv.data["headers"] == ["colA", "colB"]


@pytest.mark.asyncio
async def test_csv_multiline_quoted_records():
    """Verify CSV reader preserves embedded newlines and commas inside quoted cells."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        csv_path = root / "complex.csv"

        content = (
            'id,title,description\n'
            '1,Bug,"Line 1\nLine 2, with comma\nLine 3"\n'
            '2,Feature,"Simple text"\n'
        )
        csv_path.write_text(content, encoding="utf-8")

        reader = DocumentReaderTool()
        res = await reader.execute({"path": str(csv_path)}, {"working_directory": str(root)})
        assert res.success
        rows = res.data["rows"]
        assert len(rows) == 3
        # Check quoted cell with internal newlines
        assert rows[1][2] == "Line 1\nLine 2, with comma\nLine 3"
        assert rows[2][2] == "Simple text"


@pytest.mark.asyncio
async def test_html_styled_report_generation():
    """Verify generation of responsive HTML reports with styled tables, figures, and code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        html_path = root / "report.html"

        res = await gen.execute(
            {
                "path": str(html_path),
                "title": "Quarterly Performance",
                "format": "html",
                "sections": [
                    {
                        "heading": "Metrics Summary",
                        "body": "System benchmark results across key indicators:",
                        "table": {
                            "headers": ["Metric", "Target", "Actual"],
                            "rows": [["Throughput", "10k req/s", "14.2k req/s"]],
                        },
                        "code": "SELECT AVG(latency) FROM logs;",
                        "callout": "Peak load handled without latency spike.",
                    }
                ],
            },
            {"working_directory": str(root)},
        )
        assert res.success
        assert html_path.exists()
        html_text = html_path.read_text(encoding="utf-8")
        assert "<title>Quarterly Performance</title>" in html_text
        assert "<h2>Metrics Summary</h2>" in html_text
        assert "<table style=" in html_text
        assert "14.2k req/s" in html_text
        assert "<pre style=" in html_text
        assert "SELECT AVG(latency)" in html_text
        assert "Peak load handled without latency spike." in html_text


@pytest.mark.asyncio
async def test_markdown_report_generation():
    """Verify Markdown report generation with tables, callouts, and code blocks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gen = DocumentGeneratorTool()
        md_path = root / "summary.md"

        res = await gen.execute(
            {
                "path": str(md_path),
                "title": "Dev Sprint Review",
                "format": "markdown",
                "sections": [
                    {
                        "heading": "Deliverables",
                        "bullets": ["Merged 5 PRs", "Added regression tests"],
                        "table": {
                            "headers": ["Module", "Coverage"],
                            "rows": [["Memory", "99%"], ["Subprocess", "98%"]],
                        },
                        "code": "nemo task 'run regression'",
                        "callout": "Sprint completed ahead of schedule.",
                    }
                ],
            },
            {"working_directory": str(root)},
        )
        assert res.success
        assert md_path.exists()
        md_text = md_path.read_text(encoding="utf-8")
        assert "# Dev Sprint Review" in md_text
        assert "## Deliverables" in md_text
        assert "| Module | Coverage |" in md_text
        assert "| Memory | 99% |" in md_text
        assert "```\nnemo task 'run regression'\n```" in md_text
        assert "> **Note:** Sprint completed ahead of schedule." in md_text


@pytest.mark.asyncio
async def test_end_to_end_document_data_pipeline():
    """Verify full data pipeline: read CSV metrics -> aggregate -> generate DOCX with table/image -> verify with reader."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        reader = DocumentReaderTool()
        gen = DocumentGeneratorTool()

        # Step 1: Write raw CSV data
        raw_csv = root / "raw_benchmarks.csv"
        raw_csv.write_text("benchmark,duration_ms,status\nTest A,120,PASS\nTest B,95,PASS\nTest C,210,PASS\n", encoding="utf-8")

        # Step 2: Read raw CSV with DocumentReaderTool
        read_csv_res = await reader.execute({"path": str(raw_csv)}, {"working_directory": str(root)})
        assert read_csv_res.success
        rows = read_csv_res.data["rows"][1:]  # skip header
        total_time = sum(int(r[1]) for r in rows)
        avg_time = total_time / len(rows)

        # Step 3: Write chart image
        chart_img = root / "chart.png"
        chart_img.write_bytes(MINIMAL_PNG_BYTES)

        # Step 4: Generate stylized DOCX report
        docx_out = root / "Benchmark_Executive_Summary.docx"
        gen_res = await gen.execute(
            {
                "path": str(docx_out),
                "title": "Automated Benchmark Executive Summary",
                "author": "NEMO Automated Pipeline",
                "format": "docx",
                "sections": [
                    {
                        "heading": "Overview",
                        "body": f"Aggregated benchmark run: Total Time = {total_time}ms, Average Time = {avg_time:.1f}ms.",
                    },
                    {
                        "heading": "Detailed Metrics",
                        "table": {
                            "headers": ["Test Suite", "Duration (ms)", "Outcome"],
                            "rows": [[r[0], r[1], r[2]] for r in rows],
                        },
                        "image_path": "chart.png",
                        "caption": "Benchmark Latency Chart",
                    },
                ],
            },
            {"working_directory": str(root)},
        )
        assert gen_res.success

        # Step 5: Verify DOCX with DocumentReaderTool
        verify_res = await reader.execute({"path": str(docx_out)}, {"working_directory": str(root)})
        assert verify_res.success
        assert verify_res.data["format"] == "docx"
        assert verify_res.data["image_count"] == 1
        assert len(verify_res.data["tables"]) == 1
        assert verify_res.data["tables"][0]["rows"][0] == ["Test A", "120", "PASS"]
        assert "Average Time = 141.7ms" in verify_res.data["content"]
        assert verify_res.data["metadata"]["author"] == "NEMO Automated Pipeline"


@pytest.mark.asyncio
async def test_document_path_traversal_security():
    """Verify DocumentGeneratorTool and DocumentReaderTool reject directory traversal outside allowed roots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        policy = SecurityPolicy()
        gen = DocumentGeneratorTool(policy=policy)
        reader = DocumentReaderTool(policy=policy)

        # 1. Generation attempt into unsafe Windows system path
        unsafe_gen = await gen.execute(
            {"path": "C:/Windows/System32/hacked.docx", "title": "Attack", "format": "docx"},
            {"working_directory": str(root)},
        )
        assert unsafe_gen.success is False
        assert "access denied" in unsafe_gen.error.lower()

        # 2. Reading attempt from unsafe path
        unsafe_read = await reader.execute(
            {"path": "C:/Windows/System32/drivers/etc/hosts"},
            {"working_directory": str(root)},
        )
        assert unsafe_read.success is False
        assert "access denied" in unsafe_read.error.lower()


# 6. Public exports
__all__ = [
    "test_docx_multilevel_headings_and_structure",
    "test_docx_rich_tables_with_headers_and_empty_cells",
    "test_docx_embedded_images_and_captions",
    "test_docx_code_blocks_and_styled_callouts",
    "test_docx_metadata_author_and_title_roundtrip",
    "test_docx_raw_markdown_content_fallback",
    "test_pdf_multipage_generation_and_page_limiting",
    "test_pdf_metadata_extraction_and_encryption_check",
    "test_pdf_corrupt_file_graceful_handling",
    "test_csv_auto_sniffer_delimiters",
    "test_csv_multiline_quoted_records",
    "test_html_styled_report_generation",
    "test_markdown_report_generation",
    "test_end_to_end_document_data_pipeline",
    "test_document_path_traversal_security",
]

