import pytest

from app.services.meta_coding import MetaCodeProposal
from server.web_coding import _validate, run_web_code


def test_mermaid_proposal_is_accepted_without_python() -> None:
    proposal = MetaCodeProposal(
        title="React state flow", can_solve=True, explanation="diagram",
        artifact_type="mermaid", mermaid_code="flowchart TD\nA[Input] --> B[State]",
    )

    _validate(proposal)


def test_mermaid_proposal_cannot_be_sent_to_python_sandbox() -> None:
    proposal = MetaCodeProposal(
        title="React state flow", can_solve=True, explanation="diagram",
        artifact_type="mermaid", mermaid_code="flowchart TD\nA --> B",
    )

    with pytest.raises(ValueError, match="not Python"):
        run_web_code(proposal=proposal, payload={}, tenant_id="tenant-a", session_id=7)
