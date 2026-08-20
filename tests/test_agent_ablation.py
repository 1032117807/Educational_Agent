from evaluation.ablation import profile


def test_ablation_profile_only_changes_the_selected_capability():
    flags = profile("without_reranker")

    assert flags["reranker"] is False
    assert flags["query_rewrite"] is True
    assert flags["subagent_runtime"] is True
