import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.services.events import record_workspace_event


class GraphExecutor:
    """
    Hardcoded sequential executor for experimental graph agents.
    """

    def __init__(self, db: Session, *, workspace_id: Optional[str], user_id: Optional[str]):
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id

    def _emit_event(
        self,
        *,
        event_type: str,
        graph_id: str,
        execution_id: str,
        node_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Standardized event envelope."""
        if not self.workspace_id:
            return
        envelope = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "graph_id": graph_id,
            "execution_id": execution_id,
            "node_id": node_id,
            "payload": payload or {},
        }
        try:
            record_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                event_type=event_type,
                resource_id=graph_id,
                user_id=self.user_id,
                entity_type="graph",
                payload=envelope,
            )
            self.db.flush()
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass

    async def execute(self, agent_id: str, pipeline_config: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        execution_id = str(uuid.uuid4())
        nodes: List[Dict[str, Any]] = pipeline_config.get("nodes") or []
        if not nodes:
            nodes = [
                {"id": "email_ingest", "type": "email_ingest", "label": "Email Ingest"},
                {"id": "vector_search", "type": "vector_search", "label": "Vector Search"},
                {"id": "reranker", "type": "reranker", "label": "Reranker"},
                {"id": "task_extract", "type": "task_extract", "label": "Task Extract"},
                {"id": "brief_gen", "type": "brief_gen", "label": "Brief Generator"},
            ]

        results: Dict[str, Any] = {}
        current_payload: Any = input_data
        steps: List[Dict[str, Any]] = []

        handlers = {
            "email_ingest": self._email_ingest,
            "vector_search": self._vector_search,
            "reranker": self._reranker,
            "task_extract": self._task_extract,
            "brief_gen": self._brief_gen,
        }

        self._emit_event(
            event_type="graph.execution.started",
            graph_id=agent_id,
            execution_id=execution_id,
            payload={"status": "running", "input": input_data},
        )

        failed = False
        error_msg: Optional[str] = None

        for node in nodes:
            node_id = node.get("id") or node.get("type") or "unknown"
            node_type = node.get("type") or node_id
            handler = handlers.get(node_type, self._noop)
            node_start_ts = datetime.now(timezone.utc).isoformat()
            self._emit_event(
                event_type="graph.node.started",
                graph_id=agent_id,
                execution_id=execution_id,
                node_id=node_id,
                payload={"status": "running", "input": current_payload},
            )
            try:
                current_payload = await handler(current_payload)
                results[node_id] = current_payload
                steps.append(
                    {
                        "node_id": node_id,
                        "status": "completed",
                        "input": current_payload,
                        "output": current_payload,
                        "started_at": node_start_ts,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                self._emit_event(
                    event_type="graph.node.completed",
                    graph_id=agent_id,
                    execution_id=execution_id,
                    node_id=node_id,
                    payload={"status": "completed", "output": current_payload},
                )
            except Exception as exc:  # pragma: no cover - runtime safety
                failed = True
                error_msg = str(exc)
                steps.append(
                    {
                        "node_id": node_id,
                        "status": "failed",
                        "error": error_msg,
                        "started_at": node_start_ts,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                self._emit_event(
                    event_type="graph.node.failed",
                    graph_id=agent_id,
                    execution_id=execution_id,
                    node_id=node_id,
                    payload={"status": "failed", "error": error_msg},
                )
                raise
            finally:
                # Also broadcast legacy progress event for compatibility
                self._broadcast_progress(
                    agent_id=agent_id,
                    node_id=node_id,
                    output=current_payload,
                )

        elapsed_ms = int((time.time() - start) * 1000)
        status = "failed" if failed else "completed"
        self._emit_event(
            event_type="graph.execution.completed",
            graph_id=agent_id,
            execution_id=execution_id,
            payload={"status": status, "output": current_payload, "metrics": {"execution_time_ms": elapsed_ms}},
        )

        return {
            "execution_id": execution_id,
            "results": results,
            "steps": steps,
            "final_output": current_payload,
            "metrics": {
                "execution_time_ms": elapsed_ms,
                "nodes_executed": len(nodes),
                "status": status,
            },
        }

    async def _email_ingest(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        messages = [
            "Mock email 1: status update",
            "Mock email 2: action needed",
            "Mock email 3: reminder",
        ]
        return {"messages": messages, "input": input_data}

    async def _vector_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        msgs = payload.get("messages") or []
        return {"top_results": msgs[:10], "source": "vector_search"}

    async def _reranker(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        results = payload.get("top_results") or payload.get("messages") or []
        return {"reranked": list(reversed(results)), "source": "reranker"}

    async def _task_extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        items = payload.get("reranked") or []
        tasks = [{"title": f"Follow up on: {item}", "priority": "high"} for item in items]
        return {"tasks": tasks, "source": "task_extract"}

    async def _brief_gen(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tasks = payload.get("tasks") or []
        summary = "Summary:\n" + "\n".join(f"- {t['title']}" for t in tasks)
        return {"summary": summary, "tasks": tasks, "source": "brief_gen"}

    async def _noop(self, payload: Any) -> Any:
        return payload

    def _broadcast_progress(self, *, agent_id: str, node_id: str, output: Any) -> None:
        if not self.workspace_id:
            return
        try:
            record_workspace_event(
                self.db,
                workspace_id=self.workspace_id,
                event_type="graph.node.completed",
                resource_id=agent_id,
                user_id=self.user_id,
                entity_type="graph",
                payload={
                    "agent_id": agent_id,
                    "node_id": node_id,
                    "output": output,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.db.commit()
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass
