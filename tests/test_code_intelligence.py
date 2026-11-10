"""Self-check verification test for AST parsing, code chunking, embeddings, and knowledge graph."""

# 1. Standard library imports
from pathlib import Path
import tempfile

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.ai.embeddings import cosine_similarity
from nemo.intelligence.chunks import StructureAwareChunker
from nemo.intelligence.graph import ProjectGraphBuilder
from nemo.intelligence.parser import ASTCodeParser

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_ast_code_parser():
    """Verify AST parser extracts imports, classes, methods, and calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sample_file = Path(tmpdir) / "sample.py"
        sample_file.write_text(
            "import os\n"
            "from math import sqrt\n\n"
            "class MathService:\n"
            "    def calculate(self, x):\n"
            "        return sqrt(x)\n\n"
            "def run():\n"
            "    s = MathService()\n"
            "    return s.calculate(16)\n",
            encoding="utf-8"
        )

        parsed = ASTCodeParser.parse_python_file(sample_file)
        assert len(parsed.imports) == 2
        assert len(parsed.classes) == 1
        assert parsed.classes[0]["name"] == "MathService"
        assert len(parsed.classes[0]["methods"]) == 1
        assert len(parsed.functions) == 1
        assert parsed.functions[0]["name"] == "run"
        assert len(parsed.calls) > 0


def test_structure_aware_chunker():
    """Verify chunks align with AST class and function boundaries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sample_file = Path(tmpdir) / "sample.py"
        sample_file.write_text(
            "class A:\n    pass\n\ndef my_fn():\n    return 42\n",
            encoding="utf-8"
        )
        chunks = StructureAwareChunker.chunk_file(sample_file)
        assert len(chunks) == 2
        kinds = [c.kind for c in chunks]
        assert "class" in kinds
        assert "function" in kinds


def test_cosine_similarity():
    """Verify vector math."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert round(cosine_similarity(v1, v2), 4) == 1.0
    assert round(cosine_similarity(v1, v3), 4) == 0.0


def test_knowledge_graph_builder():
    """Verify graph builder constructs nodes and Cypher statements."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        f = root / "mod.py"
        f.write_text("def helper(): pass\n", encoding="utf-8")

        graph = ProjectGraphBuilder.build_graph(project_name="TestProj", root_path=root, python_files=[f])
        assert len(graph.nodes) >= 3  # Project, File, Symbol
        assert len(graph.edges) >= 2  # CONTAINS, DECLARES

        cypher = ProjectGraphBuilder.export_cypher(graph)
        assert len(cypher) > 0
        assert any("MERGE" in q for q in cypher)


def main():
    print("Running Code Intelligence (AST, Chunks, Embeddings, Graph) verification...")
    test_ast_code_parser()
    print("✓ AST code parser checks passed!")
    test_structure_aware_chunker()
    print("✓ Structure-aware chunker checks passed!")
    test_cosine_similarity()
    print("✓ Cosine similarity checks passed!")
    test_knowledge_graph_builder()
    print("✓ Knowledge graph builder and Cypher export checks passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = [
    "test_ast_code_parser",
    "test_structure_aware_chunker",
    "test_cosine_similarity",
    "test_knowledge_graph_builder",
]
