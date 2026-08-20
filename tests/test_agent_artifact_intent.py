from server.agent_stream import _human_input_request, _model_artifact_decision, _requested_artifact


def test_report_analysis_does_not_create_a_file() -> None:
    assert _requested_artifact("分析我的本周学习报告", ["learning_report"]) is None


def test_explicit_report_export_creates_markdown_artifact() -> None:
    assert _requested_artifact("请生成一份可下载的 Markdown 学习报告", ["learning_report"]) == "markdown_report"


def test_download_location_question_does_not_create_a_new_report() -> None:
    assert _requested_artifact("我之前下载的报告在哪里？", ["learning_report"]) is None


def test_external_document_download_does_not_become_a_report() -> None:
    assert _requested_artifact("帮我下载高等数学资料 pdf 或 word 文件", []) is None


class _ModelResponse:
    content = '{"create_report_file": true}'


class _DecisionModel:
    def invoke(self, _prompt: str) -> _ModelResponse:
        return _ModelResponse()


def test_model_decision_is_primary_artifact_classifier() -> None:
    assert _model_artifact_decision(_DecisionModel(), message="请保存这份总结", actions=["chat"]) == "markdown_report"


def test_web_resource_request_without_results_asks_the_user() -> None:
    decision = _human_input_request(None, message="请联网下载高等数学 PDF 资料", web_results=[])
    assert decision is not None
    assert decision["options"]
