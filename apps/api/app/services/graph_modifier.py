import json
from typing import Any, Dict, List, Tuple

from config import openai_client
from models import User
from app.models.graph_agent import GraphAgent, GraphHistory
from sqlalchemy.orm import Session
from datetime import datetime, timezone


class PipelineModifier:
    def __init__(self, db: Session, current_user: User):
        self.db = db
        self.current_user = current_user

    async def modify_from_request(
        self,
        agent: GraphAgent,
        user_request: str,
    ) -> Dict[str, Any]:
        current_pipeline = agent.pipeline_config or {}
        llm_output = await self._call_llm(user_request, current_pipeline)
        new_pipeline = llm_output.get("pipeline") or current_pipeline
        explanation = llm_output.get("explanation") or "No changes"

        self._validate_pipeline(new_pipeline)

        new_version = (agent.version or 1) + 1
        diff = self._diff_pipelines(current_pipeline, new_pipeline)

        # Save history before mutating
        history = GraphHistory(
            agent_id=agent.id,
            version=new_version,
            pipeline_config=new_pipeline,
            change_summary=explanation,
            created_by=getattr(self.current_user, "id", None),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(history)

        agent.pipeline_config = new_pipeline
        agent.version = new_version
        agent.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        return {
            "new_pipeline": new_pipeline,
            "explanation": explanation,
            "diff": diff,
            "version": new_version,
        }

    async def _call_llm(self, user_request: str, current_pipeline: Dict[str, Any]) -> Dict[str, Any]:
        if not openai_client:
            return {
                "pipeline": current_pipeline,
                "explanation": "OpenAI client not configured; pipeline unchanged",
            }
        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "You modify agent pipelines. Given current pipeline and user request, output JSON with fields: pipeline, explanation, diff",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"request": user_request, "current_pipeline": current_pipeline}
                        ),
                    },
                ],
                max_tokens=400,
            )
            content = resp.choices[0].message.content
            return json.loads(content) if content else {}
        except Exception:
            return {
                "pipeline": current_pipeline,
                "explanation": "LLM modification failed; pipeline unchanged",
            }

    def _validate_pipeline(self, pipeline: Dict[str, Any]) -> None:
        nodes = pipeline.get("nodes") or []
        edges = pipeline.get("edges") or []

        node_ids = [n.get("id") for n in nodes if n.get("id")]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Duplicate node ids in pipeline")

        node_set = set(node_ids)
        for edge in edges:
            if edge.get("source") not in node_set or edge.get("target") not in node_set:
                raise ValueError("Edge references unknown node")

        if self._has_cycle(node_set, edges):
            raise ValueError("Pipeline contains cycles")

    def _has_cycle(self, node_ids: set, edges: List[Dict[str, Any]]) -> bool:
        graph = {n: [] for n in node_ids}
        for edge in edges:
            s = edge.get("source")
            t = edge.get("target")
            if s in graph and t:
                graph[s].append(t)

        visited = set()
        stack = set()

        def dfs(node: str) -> bool:
            if node in stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            stack.add(node)
            for neigh in graph.get(node, []):
                if dfs(neigh):
                    return True
            stack.remove(node)
            return False

        return any(dfs(n) for n in node_ids)

    def _diff_pipelines(self, old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        old_nodes = {n.get("id"): n for n in old.get("nodes", []) if n.get("id")}
        new_nodes = {n.get("id"): n for n in new.get("nodes", []) if n.get("id")}

        added = [n for nid, n in new_nodes.items() if nid not in old_nodes]
        removed = [n for nid, n in old_nodes.items() if nid not in new_nodes]
        modified = [
            {"id": nid, "from": old_nodes[nid], "to": new_nodes[nid]}
            for nid in new_nodes
            if nid in old_nodes and new_nodes[nid] != old_nodes[nid]
        ]

        def edge_set(p):
            return {(e.get("source"), e.get("target")) for e in p.get("edges", [])}

        old_edges = edge_set(old)
        new_edges = edge_set(new)

        edge_added = [e for e in new_edges if e not in old_edges]
        edge_removed = [e for e in old_edges if e not in new_edges]

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "edges_added": list(edge_added),
            "edges_removed": list(edge_removed),
        }
