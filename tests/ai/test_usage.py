from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, Generation, LLMResult

from ai.chains.run_state import fail_run, finish_run
from ai.usage import UsageCollector, track_usage
from app.models import AIRun


def test_usage_collector_reads_openai_compatible_llm_output() -> None:
    collector = UsageCollector()
    response = LLMResult(
        generations=[[Generation(text="ok")]],
        llm_output={"token_usage": {"prompt_tokens": 13, "completion_tokens": 7}},
    )

    with track_usage() as usage:
        collector.on_llm_end(response)

    assert (usage.input_tokens, usage.output_tokens, usage.call_count) == (13, 7, 1)


def test_usage_collector_reads_streaming_message_metadata() -> None:
    collector = UsageCollector()
    generation = ChatGeneration(message=AIMessage(
        content="ok", usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
    ))
    response = LLMResult(generations=[[generation]], llm_output={})

    with track_usage() as usage:
        collector.on_llm_end(response)

    assert (usage.input_tokens, usage.output_tokens, usage.call_count) == (5, 3, 1)


def test_run_state_persists_usage_on_success_and_failure() -> None:
    run = AIRun(
        run_uuid=str(uuid4()), feature="test", status="running", provider="test",
        model_name="test", prompt_version="test",
    )
    with track_usage() as usage:
        usage.add(input_tokens=11, output_tokens=4)
    finish_run(run, output_json='{"ok":true}', usage=usage)
    assert (run.status, run.input_tokens, run.output_tokens) == ("completed", 11, 4)
    assert run.finished_at is not None and run.finished_at.tzinfo is not None

    fail_run(run, error_message="failed", usage=usage)
    assert (run.status, run.input_tokens, run.output_tokens) == ("failed", 11, 4)
