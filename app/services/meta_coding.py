"""Constrained Coding Agent meta-capability.

Temporary code is executed only through the existing no-network, read-only
Docker sandbox.  Persisting a reusable Skill always requires a UI confirmation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.services.mcp_gateway import MCPGateway


class MetaCodeProposal(BaseModel):
    """The only structured output accepted from the Coding Agent."""

    title: str = Field(min_length=2, max_length=120)
    can_solve: bool
    explanation: str = Field(min_length=1, max_length=800)
    python_code: str = Field(default="", max_length=12_000)
    artifact_type: Literal["python", "mermaid"] = "python"
    mermaid_code: str = Field(default="", max_length=12_000)
    # Providers occasionally return a compact JSON example plus a short
    # explanation.  Keep the UI concise, but do not reject an otherwise safe
    # proposal before the server can validate its code.
    expected_output: str = Field(default="", max_length=1200)
    publishable: bool = False
    skill_name: str = ""
    skill_description: str = Field(default="", max_length=500)
    skill_script: str = Field(default="", max_length=16_000)


@dataclass(frozen=True)
class MetaExecutionResult:
    """A safe, user-visible result of one temporary sandbox execution."""

    proposal: MetaCodeProposal
    stdout: str
    stderr: str
    returncode: int


META_CODING_PROMPT = """
You are the constrained Coding Agent for a desktop learning application.
Use this ability only when the available tools and enabled Skills cannot solve
the user's request. Produce temporary Python that operates only on `payload`.
For learning analysis, `payload["learning_snapshot"]` contains a bounded,
read-only snapshot of recent study, task, attempt, and knowledge-point data.

Safety rules:
1. The program runs in a no-network, read-only Docker sandbox.
2. Do not access files, network, subprocesses, dynamic imports, eval, or exec.
3. `python_code` can use the preloaded `payload` dict and `json` module.
4. `python_code` must print a JSON string as its final output.
5. Never claim the code has already run.
6. Set publishable only for a genuinely reusable capability. In that case,
   skill_script must read JSON from sys.stdin and print JSON to sys.stdout.
7. skill_name may contain only lowercase letters, digits, and hyphens.
Return concise Chinese explanation text for the user.
""".strip()


class MetaCodingService:
    """Generate, validate, run, and optionally publish Coding Agent work."""

    SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
    BLOCKED_CODE_PATTERNS = (
        r"\bimport\s+os\b", r"\bfrom\s+os\b", r"\bsubprocess\b",
        r"\bsocket\b", r"\brequests\b", r"\burllib\b", r"\bpathlib\b",
        r"\bshutil\b", r"\bopen\s*\(", r"\beval\s*\(",
        r"\bexec\s*\(", r"__import__\s*\(", r"\bctypes\b",
    )

    def __init__(
        self,
        *,
        chat_model: BaseChatModel,
        mcp_gateway: MCPGateway,
        skills_dir: Path,
    ) -> None:
        self.mcp_gateway = mcp_gateway
        self.skills_dir = skills_dir.resolve()
        try:
            self.model = chat_model.with_structured_output(
                MetaCodeProposal, method="function_calling", strict=False
            )
        except TypeError:
            self.model = chat_model.with_structured_output(MetaCodeProposal)

    def propose(
        self,
        *,
        request: str,
        available_tools: list[dict],
        available_skills: list[dict],
        payload: dict | None = None,
    ) -> MetaCodeProposal:
        """Ask the model for code, but do not execute or write anything yet."""
        prompt = (
            f"{META_CODING_PROMPT}\n\n"
            f"User request:\n{request.strip()}\n\n"
            f"Available tools:\n{json.dumps(available_tools, ensure_ascii=False)}\n\n"
            f"Enabled Skills:\n{json.dumps(available_skills, ensure_ascii=False)}\n\n"
            f"Payload supplied to temporary code:\n"
            f"{json.dumps(payload or {}, ensure_ascii=False)}"
        )
        proposal = MetaCodeProposal.model_validate(self.model.invoke(prompt))
        self._validate_proposal(proposal)
        return proposal

    def run_temporary(
        self, *, proposal: MetaCodeProposal, payload: dict | None = None
    ) -> MetaExecutionResult:
        """Run generated code automatically inside the constrained sandbox."""
        self._validate_proposal(proposal)
        if not proposal.can_solve:
            raise ValueError("Coding Agent 判断该任务不能在安全沙箱中完成")
        if not proposal.python_code.strip():
            raise ValueError("临时代码为空")

        # payload is the only data supplied to generated code.  It cannot read
        # arbitrary project files or use the network from the sandbox.
        program = (
            "import json\n"
            f"payload = json.loads({json.dumps(json.dumps(payload or {}, ensure_ascii=False))})\n"
            "# 以下代码由 Coding Agent 生成并在只读沙箱中执行。\n"
            f"{proposal.python_code.strip()}\n"
        )
        response = self.mcp_gateway.execute(
            "run_python_in_sandbox", {"code": program}, confirmed=False
        )
        raw = "\n".join(str(item) for item in response.get("content", []))
        try:
            sandbox = json.loads(raw)
        except json.JSONDecodeError:
            sandbox = {"returncode": 1, "stdout": "", "stderr": raw}
        return MetaExecutionResult(
            proposal=proposal,
            stdout=str(sandbox.get("stdout", "")),
            stderr=str(sandbox.get("stderr", "")),
            returncode=int(sandbox.get("returncode", 1)),
        )

    def publish_skill(self, *, proposal: MetaCodeProposal, confirmed: bool) -> Path:
        """Persist a reusable Skill only after the UI has explicit confirmation."""
        if not confirmed:
            raise PermissionError("发布新 Skill 必须由用户确认")
        self._validate_proposal(proposal)
        if not proposal.publishable:
            raise ValueError("该方案未标记为可发布 Skill")
        if not proposal.skill_script.strip():
            raise ValueError("可发布 Skill 缺少可执行脚本")
        self._validate_code(proposal.skill_script)

        skill_dir = (self.skills_dir / proposal.skill_name).resolve()
        if self.skills_dir not in skill_dir.parents:
            raise PermissionError("Skill 路径越界")
        if skill_dir.exists():
            raise ValueError(f"Skill 已存在：{proposal.skill_name}")

        script_dir = skill_dir / "scripts"
        script_dir.mkdir(parents=True, exist_ok=False)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {proposal.skill_name}\n"
            f"description: {proposal.skill_description}\n---\n\n"
            f"# {proposal.title}\n\n"
            "由 Coding Agent 生成；修改后必须在沙箱验证。\n"
            "脚本从标准输入读取 JSON，并向标准输出返回 JSON。\n",
            encoding="utf-8",
        )
        (skill_dir / "skill.json").write_text(json.dumps({
            "version": "1.0.0",
            "entrypoint": "scripts/main.py",
            "description": proposal.skill_description,
            "input_schema": {"type": "object"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (script_dir / "main.py").write_text(
            proposal.skill_script.strip() + "\n", encoding="utf-8"
        )
        return skill_dir

    def _validate_proposal(self, proposal: MetaCodeProposal) -> None:
        if proposal.can_solve:
            self._validate_code(proposal.python_code)
        if proposal.publishable:
            if not self.SKILL_NAME_PATTERN.fullmatch(proposal.skill_name):
                raise ValueError("Skill 名称只允许小写字母、数字和连字符")
            if not proposal.skill_description.strip():
                raise ValueError("Skill 描述不能为空")

    def _validate_code(self, code: str) -> None:
        if not code.strip():
            raise ValueError("代码为空")
        if len(code) > 16_000:
            raise ValueError("代码过长")
        for pattern in self.BLOCKED_CODE_PATTERNS:
            if re.search(pattern, code, flags=re.IGNORECASE):
                raise PermissionError(f"代码包含不允许的能力：{pattern}")
