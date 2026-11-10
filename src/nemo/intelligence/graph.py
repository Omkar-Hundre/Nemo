"""Knowledge graph models and Cypher/Neo4j query projections for code architecture."""

# 1. Standard library imports
from pathlib import Path
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.intelligence.parser import ASTCodeParser, ParsedModule

# 4. Types, Protocols, Schemas
class GraphNode(BaseModel):
    id: str
    label: str  # Project, File, Symbol, Package
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    rel_type: str  # CONTAINS, DECLARES, IMPORTS, CALLS
    properties: dict[str, Any] = Field(default_factory=dict)


class CodeKnowledgeGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

    def find_callers(self, target_name: str) -> list[dict[str, Any]]:
        """Find all caller symbols and files that invoke a target function or method."""
        target_lower = target_name.lower()
        matches = []
        for e in self.edges:
            if e.rel_type == "CALLS":
                # Match target in call target id (e.g. call:target_name)
                if target_lower in e.target_id.lower():
                    source_node = next((n for n in self.nodes if n.id == e.source_id), None)
                    matches.append({
                        "caller_id": e.source_id,
                        "caller_name": source_node.properties.get("name") if source_node else e.source_id,
                        "file": source_node.properties.get("file") if source_node else "-",
                        "target_called": e.target_id.replace("call:", ""),
                    })
        return matches

    def find_callees(self, caller_name: str) -> list[dict[str, Any]]:
        """Find all functions/methods called by a given caller symbol."""
        caller_lower = caller_name.lower()
        matches = []
        for e in self.edges:
            if e.rel_type == "CALLS":
                if caller_lower in e.source_id.lower():
                    matches.append({
                        "caller_id": e.source_id,
                        "called_target": e.target_id.replace("call:", ""),
                    })
        return matches

    def find_imports(self, target_module: str = "") -> list[dict[str, Any]]:
        """Find file dependencies and imported packages."""
        mod_lower = target_module.lower()
        matches = []
        for e in self.edges:
            if e.rel_type == "IMPORTS":
                if not mod_lower or mod_lower in e.target_id.lower() or mod_lower in e.source_id.lower():
                    matches.append({
                        "file": e.source_id.replace("file:", ""),
                        "imported_package": e.target_id.replace("pkg:", ""),
                    })
        return matches

    def find_declarations(self, name_filter: str = "", kind: str = "") -> list[dict[str, Any]]:
        """Find declared classes, functions, or methods in the graph."""
        n_lower = name_filter.lower()
        k_lower = kind.lower()
        results = []
        for n in self.nodes:
            if n.label == "Symbol":
                name = n.properties.get("name", "")
                k = n.properties.get("kind", "")
                if (not n_lower or n_lower in name.lower()) and (not k_lower or k_lower == k.lower()):
                    results.append({
                        "id": n.id,
                        "name": name,
                        "kind": k,
                        "file": n.properties.get("file", "-"),
                    })
        return results

# 5. Core logic / classes / functions
class ProjectGraphBuilder:
    """Constructs architectural knowledge graph from files, symbols, imports, and calls."""

    @staticmethod
    def build_graph(project_name: str, root_path: Path | str, python_files: list[Path]) -> CodeKnowledgeGraph:
        graph = CodeKnowledgeGraph()
        proj_id = f"proj:{project_name}"
        graph.nodes.append(GraphNode(id=proj_id, label="Project", properties={"name": project_name, "root": str(root_path)}))

        for file_path in python_files:
            rel = str(file_path.relative_to(root_path)).replace("\\", "/")
            file_id = f"file:{rel}"
            graph.nodes.append(GraphNode(id=file_id, label="File", properties={"path": rel}))
            graph.edges.append(GraphEdge(source_id=proj_id, target_id=file_id, rel_type="CONTAINS"))

            # Parse AST
            parsed: ParsedModule = ASTCodeParser.parse_python_file(file_path)

            # Classes and methods
            for cls in parsed.classes:
                cls_id = f"sym:{rel}:{cls['name']}"
                graph.nodes.append(GraphNode(id=cls_id, label="Symbol", properties={"name": cls["name"], "kind": "class", "file": rel}))
                graph.edges.append(GraphEdge(source_id=file_id, target_id=cls_id, rel_type="DECLARES"))

                for method in cls.get("methods", []):
                    m_id = f"sym:{rel}:{cls['name']}.{method['name']}"
                    graph.nodes.append(GraphNode(id=m_id, label="Symbol", properties={"name": f"{cls['name']}.{method['name']}", "kind": "method", "file": rel}))
                    graph.edges.append(GraphEdge(source_id=cls_id, target_id=m_id, rel_type="DECLARES"))

            # Functions
            for fn in parsed.functions:
                fn_id = f"sym:{rel}:{fn['name']}"
                graph.nodes.append(GraphNode(id=fn_id, label="Symbol", properties={"name": fn["name"], "kind": "function", "file": rel}))
                graph.edges.append(GraphEdge(source_id=file_id, target_id=fn_id, rel_type="DECLARES"))

            # Imports
            for imp in parsed.imports:
                imp_id = f"pkg:{imp.module}"
                graph.nodes.append(GraphNode(id=imp_id, label="Package", properties={"name": imp.module}))
                graph.edges.append(GraphEdge(source_id=file_id, target_id=imp_id, rel_type="IMPORTS"))

            # Calls
            for call in parsed.calls:
                call_target_id = f"call:{call.target_name}"
                graph.edges.append(GraphEdge(source_id=f"sym:{rel}:{call.caller_symbol}", target_id=call_target_id, rel_type="CALLS"))

        return graph

    @staticmethod
    def export_cypher(graph: CodeKnowledgeGraph) -> list[str]:
        """Generate Cypher statements for importing into Neo4j."""
        statements = []
        for n in graph.nodes:
            props = ", ".join(f"{k}: '{v}'" for k, v in n.properties.items())
            statements.append(f"MERGE (n:{n.label} {{id: '{n.id}'}}) ON CREATE SET n += {{{props}}};")
        for e in graph.edges:
            statements.append(f"MATCH (a {{id: '{e.source_id}'}}), (b {{id: '{e.target_id}'}}) MERGE (a)-[:{e.rel_type}]->(b);")
        return statements

# 6. Public exports
__all__ = ["GraphNode", "GraphEdge", "CodeKnowledgeGraph", "ProjectGraphBuilder"]

