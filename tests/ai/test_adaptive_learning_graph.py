from ai.agents.adaptive_learning_graph import AdaptiveLearningGraph


def test_wrong_answers_route_to_remediation_and_record_negotiation():
    calls = []
    graph = AdaptiveLearningGraph(
        assess=lambda state: state["answers"],
        negotiate=lambda state: calls.append("negotiate") or {"decision": "remediate", "agents": ["assessment", "plan"]},
        remediate=lambda state: {"practice_question_ids": [11, 12]},
        advance=lambda state: {"completed_topics": [1]},
        revise_plan=lambda state: {"reason": "weak mastery"},
    )

    result = graph.invoke({"answers": [{"knowledge_point_id": 1, "correct": False, "mastery": 35}]})

    assert calls == ["negotiate"]
    assert result["next_action"] == "remediate"
    assert result["practice_question_ids"] == [11, 12]
    assert result["round"] == 1
    assert result["plan_updates"] == [{"reason": "weak mastery"}]


def test_mastered_answers_advance_and_end_current_round():
    graph = AdaptiveLearningGraph(
        assess=lambda state: state["answers"],
        remediate=lambda state: {"practice_question_ids": [99]},
        advance=lambda state: {"completed_topics": [3]},
        revise_plan=lambda state: {"reason": "mastered"},
    )

    result = graph.invoke({"answers": [{"knowledge_point_id": 3, "correct": True, "mastery": 85}]})

    assert result["next_action"] == "advance"
    assert result["completed_topics"] == [3]
    assert result["round"] == 1
