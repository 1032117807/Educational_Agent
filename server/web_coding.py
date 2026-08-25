"""Durable, constrained Coding Agent operations for the Web client."""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.services.meta_coding import MetaCodeProposal
from server.agent_tools import WebAgentToolExecutor


_BLOCKED_CODE_PATTERNS = (
    r"\bimport\s+os\b", r"\bfrom\s+os\b", r"\bsubprocess\b",
    r"\bsocket\b", r"\brequests\b", r"\burllib\b", r"\bpathlib\b",
    r"\bshutil\b", r"\bopen\s*\(", r"\beval\s*\(",
    r"\bexec\s*\(", r"__import__\s*\(", r"\bctypes\b",
)


def propose_web_code(*, model: BaseChatModel, request: str, payload: dict[str, Any]) -> MetaCodeProposal:
    """Produce a temporary program which can only use the supplied payload."""
    prompt = (
        "You are the Web Coding Agent for a learning application. Return the MetaCodeProposal schema. "
        "Write concise Chinese explanation. For diagram requests, set artifact_type=mermaid and return only valid Mermaid flowchart/sequence/class syntax in mermaid_code; do not generate Python for it. "
        "For computation requests, set artifact_type=python. The Python program may use only json and the preloaded payload dict, "
        "must print one JSON result, and must not access files, network, subprocesses, dynamic imports, eval, or exec. "
        "Set publishable=false: deployed Web containers do not persist new Skills at runtime.\n"
        f"Request: {request.strip()}\nPayload: {json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        structured = model.with_structured_output(MetaCodeProposal, method="function_calling", strict=False)
    except TypeError:
        structured = model.with_structured_output(MetaCodeProposal)
    proposal = MetaCodeProposal.model_validate(structured.invoke(prompt))
    _validate(proposal)
    return proposal


def run_web_code(*, proposal: MetaCodeProposal, payload: dict[str, Any], tenant_id: str, session_id: int) -> dict[str, Any]:
    _validate(proposal)
    if proposal.artifact_type != "python":
        raise ValueError("Mermaid diagrams are saved in the workspace; they are not Python programs")
    if not proposal.can_solve or not proposal.python_code.strip():
        raise ValueError("Coding Agent did not produce runnable temporary code")
    program = (
        "import json\n"
        f"payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))})\n"
        f"{proposal.python_code.strip()}\n"
    )
    result = WebAgentToolExecutor(tenant_id=tenant_id, session_id=session_id).run_python(program)
    return {"returncode": int(result["returncode"]), "stdout": str(result["stdout"]), "stderr": str(result["stderr"])}


def _validate(proposal: MetaCodeProposal) -> None:
    if proposal.artifact_type == "mermaid":
        if not proposal.mermaid_code.strip():
            raise ValueError("generated Mermaid diagram is empty")
        if not re.match(r"^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt)\b", proposal.mermaid_code):
            raise ValueError("generated Mermaid diagram has an unsupported format")
        return
    if len(proposal.python_code) > 16_000:
        raise ValueError("generated code is too long")
    for pattern in _BLOCKED_CODE_PATTERNS:
        if re.search(pattern, proposal.python_code, flags=re.IGNORECASE):
            raise PermissionError("generated code contains a disallowed capability")
