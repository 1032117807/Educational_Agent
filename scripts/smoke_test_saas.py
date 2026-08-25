"""Run a disposable black-box SaaS learning-loop smoke test.

This intentionally creates one uniquely named test workspace. Run it only
against a local or staging deployment, never against a real tenant database.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from uuid import uuid4


def call(base_url: str, path: str, *, token: str = "", method: str = "GET", payload: dict | None = None) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=body, method=method)
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {path} returned {exc.code}: {detail}") from exc


def upload_resource(base_url: str, *, token: str, course_id: int, filename: str, content: bytes) -> dict:
    """Exercise the real multipart upload boundary without external libraries."""
    boundary = f"----learning-smoke-{uuid4().hex}"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="course_id"\r\n\r\n', str(course_id).encode(), b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: text/plain\r\n\r\n", content, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(f"{base_url.rstrip('/')}/v1/resources", data=body, method="POST")
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"POST /v1/resources returned {exc.code}: {detail}") from exc


def wait_for_ready(base_url: str, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            result = call(base_url, "/health/ready")
            if isinstance(result, dict) and result.get("status") == "ready":
                return
            last_error = f"unexpected readiness response: {result!r}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"SaaS API readiness timeout: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SAAS_BASE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    wait_for_ready(args.base_url)
    suffix = uuid4().hex[:12]
    email = f"smoke-{suffix}@example.test"
    password = secrets.token_urlsafe(18) + "Aa1!"
    registered = call(args.base_url, "/v1/auth/register", method="POST", payload={
        "email": email, "password": password, "organization_name": f"Smoke {suffix}", "display_name": "SaaS Smoke",
    })
    token = str(registered["access_token"])
    course = call(args.base_url, "/v1/courses", token=token, method="POST", payload={
        "name": "Smoke Calculus", "subject": "Mathematics", "description": "Disposable runtime verification",
    })
    course_id = int(course["id"])
    goal = call(args.base_url, "/v1/goals", token=token, method="POST", payload={
        "title": "Smoke goal", "target_date": (date.today() + timedelta(days=30)).isoformat(),
        "weekly_minutes": 120, "course_id": course_id,
    })
    point = call(args.base_url, "/v1/knowledge-points", token=token, method="POST", payload={
        "course_id": course_id, "name": "Smoke limits", "definition": "Disposable knowledge point",
    })
    task = call(args.base_url, "/v1/tasks", token=token, method="POST", payload={
        "title": "Smoke task", "planned_date": date.today().isoformat(), "duration_minutes": 15,
        "course_id": course_id, "knowledge_point_id": point["id"],
    })
    task_rows = call(args.base_url, "/v1/tasks", token=token)
    question = call(args.base_url, "/v1/questions", token=token, method="POST", payload={
        "course_id": course_id, "knowledge_point_id": point["id"], "prompt": "Smoke answer?",
        "answer": "A", "kind": "single_choice", "options": "A\nB", "difficulty": 2,
    })
    practice = call(args.base_url, "/v1/practice-sessions", token=token, method="POST", payload={
        "course_id": course_id, "question_ids": [question["id"]],
    })
    attempt = call(args.base_url, f"/v1/practice-sessions/{practice['id']}/questions/{question['id']}/attempts",
                   token=token, method="POST", payload={"response": "B", "elapsed_seconds": 4})
    summary = call(args.base_url, f"/v1/practice-sessions/{practice['id']}/complete", token=token, method="POST")
    multiple_choice = call(args.base_url, "/v1/questions", token=token, method="POST", payload={
        "course_id": course_id, "knowledge_point_id": point["id"], "prompt": "Select smoke options.",
        "answer": "A, C", "kind": "multiple_choice", "options": "A. First\nB. Second\nC. Third", "difficulty": 2,
    })
    multiple_practice = call(args.base_url, "/v1/practice-sessions", token=token, method="POST", payload={
        "course_id": course_id, "question_ids": [multiple_choice["id"]],
    })
    multiple_attempt = call(
        args.base_url, f"/v1/practice-sessions/{multiple_practice['id']}/questions/{multiple_choice['id']}/attempts",
        token=token, method="POST", payload={"response": "C. Third\nA. First", "elapsed_seconds": 4},
    )
    call(args.base_url, f"/v1/practice-sessions/{multiple_practice['id']}/complete", token=token, method="POST")
    knowledge_points = call(args.base_url, f"/v1/knowledge-points?course_id={course_id}", token=token)
    mistakes = call(args.base_url, "/v1/mistakes", token=token)
    today = call(args.base_url, "/v1/today", token=token)
    analytics = call(args.base_url, "/v1/analytics?days=all", token=token)
    reminders = call(args.base_url, "/v1/reminders", token=token)
    started = call(args.base_url, f"/v1/tasks/{task['id']}/action", token=token, method="POST", payload={"action": "start"})
    workspace = call(args.base_url, f"/v1/courses/{course_id}/workspace", token=token)
    resource_upload = upload_resource(
        args.base_url, token=token, course_id=course_id, filename="smoke-notes.txt",
        content=b"Smoke limit review material: learn definitions before examples.",
    )
    resources = call(args.base_url, f"/v1/resources?course_id={course_id}", token=token)
    resource_question_job = call(args.base_url, "/v1/ai/question-generation/jobs", token=token, method="POST", payload={
        "course_id": course_id, "resource_ids": [resource_upload["resource_id"]],
        "request": "Create disposable questions grounded in the uploaded smoke material.",
        "count": 2, "difficulty": 2, "kinds": ["single_choice"],
    })
    rag_job = call(args.base_url, "/v1/rag/jobs", token=token, method="POST", payload={
        "question": "What should I review next?", "course_id": course_id,
    })
    ai_job = call(args.base_url, "/v1/ai/jobs", token=token, method="POST", payload={
        "feature": "learning_report", "course_id": course_id, "request": "Summarize this disposable workspace.",
    })
    agent_session = call(args.base_url, "/v1/agent/sessions", token=token, method="POST", payload={
        "title": "Smoke Agent Compatibility",
    })
    learning_launch = call(
        args.base_url, f"/v1/agent/sessions/{agent_session['id']}/learning-launch",
        token=token, method="POST", payload={
            "title": "Smoke adaptive plan", "request": "Review limits and build a short practice plan.",
            "course_id": course_id, "target_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_minutes": 90, "question_count": 2, "vocabulary_count": 2,
        },
    )
    auto_course_request = "制定未来 7 天每日任务，围绕极限的定义安排练习。"
    auto_session = call(args.base_url, "/v1/agent/sessions", token=token, method="POST", payload={
        "title": "Smoke automatic course",
    })
    auto_launch = call(
        args.base_url, f"/v1/agent/sessions/{auto_session['id']}/learning-launch",
        token=token, method="POST", payload={
            "title": "Smoke automatic calculus plan", "request": auto_course_request,
            "target_date": (date.today() + timedelta(days=6)).isoformat(),
            "weekly_minutes": 90, "question_count": 2, "vocabulary_count": 2,
        },
    )
    repeat_session = call(args.base_url, "/v1/agent/sessions", token=token, method="POST", payload={
        "title": "Smoke automatic course repeat",
    })
    repeat_auto_launch = call(
        args.base_url, f"/v1/agent/sessions/{repeat_session['id']}/learning-launch",
        token=token, method="POST", payload={
            "title": "Smoke automatic calculus plan repeat", "request": auto_course_request,
            "target_date": (date.today() + timedelta(days=6)).isoformat(),
            "weekly_minutes": 90, "question_count": 2, "vocabulary_count": 2,
        },
    )
    auto_course_workspace = call(args.base_url, f"/v1/courses/{auto_launch['course_id']}/workspace", token=token)
    agent_tools = call(args.base_url, "/v1/agent/tools", token=token)
    agent_search = call(args.base_url, "/v1/agent/tools/search?q=learning", token=token)
    memory = call(args.base_url, "/v1/agent/memories", token=token, method="POST", payload={
        "scope": "course", "category": "weak_point", "course_id": course_id,
        "content": {"note": "Smoke memory"}, "confirmed": True,
    })
    memories = call(args.base_url, f"/v1/agent/memories?course_id={course_id}", token=token)
    call(args.base_url, f"/v1/agent/memories/{memory['id']}", token=token, method="DELETE")
    note = call(args.base_url, f"/v1/courses/{course_id}/notes", token=token, method="POST", payload={
        "title": "Smoke note", "content": "Disposable course note",
    })
    notes = call(args.base_url, f"/v1/courses/{course_id}/notes", token=token)
    updated_note = call(args.base_url, f"/v1/course-notes/{note['id']}", token=token, method="PATCH", payload={
        "content": "Updated disposable course note",
    })
    call(args.base_url, f"/v1/course-notes/{note['id']}", token=token, method="DELETE")
    action = call(args.base_url, f"/v1/tasks/{task['id']}/action", token=token, method="POST", payload={"action": "complete"})
    if attempt.get("correct") is not False or summary.get("correct") != 0:
        raise RuntimeError("practice result did not record the intentional wrong answer")
    if multiple_attempt.get("correct") is not True:
        raise RuntimeError("multiple-choice result did not normalize the selected answer set")
    learning_point = next((item for item in knowledge_points if item.get("id") == point["id"]), None)
    if not learning_point or learning_point.get("practice_count") != 2 or "prerequisites" not in learning_point:
        raise RuntimeError("knowledge workspace response did not expose updated mastery metadata")
    if not mistakes or not today.get("tasks") or analytics.get("range", {}).get("days") != "all":
        raise RuntimeError(
            "learning loop response was incomplete: "
            f"mistakes={len(mistakes) if isinstance(mistakes, list) else 'invalid'}, "
            f"today_tasks={len(today.get('tasks', [])) if isinstance(today, dict) and isinstance(today.get('tasks'), list) else 'invalid'}, "
            f"analytics_range={analytics.get('range') if isinstance(analytics, dict) else 'invalid'}"
        )
    listed_task = next((item for item in task_rows if item.get("id") == task["id"]), None)
    if not listed_task or listed_task.get("course_name") != "Smoke Calculus" or listed_task.get("knowledge_point_name") != "Smoke limits" or listed_task.get("source") != "user":
        raise RuntimeError("task provenance response was incomplete")
    if started.get("status") != "in_progress" or not workspace.get("recent_tasks") or workspace.get("mistake_count") < 1:
        raise RuntimeError("task lifecycle or course workspace response was incomplete")
    if action.get("completed") is not True:
        raise RuntimeError("task action did not complete the task")
    if len(notes) != 1 or updated_note.get("content") != "Updated disposable course note":
        raise RuntimeError("course note CRUD response was incomplete")
    if (not isinstance(resources, list) or not any(item.get("id") == resource_upload["resource_id"] for item in resources)
            or not isinstance(rag_job, dict) or rag_job.get("status") != "queued"):
        raise RuntimeError("RAG compatibility boundary did not queue a job")
    if not isinstance(resource_question_job, dict) or resource_question_job.get("status") != "queued":
        raise RuntimeError("resource-grounded question generation did not queue a job")
    if not isinstance(ai_job, dict) or ai_job.get("status") != "queued":
        raise RuntimeError("AI Center compatibility boundary did not queue a job")
    if not isinstance(agent_session, dict) or not agent_session.get("id") or not agent_tools or not agent_search:
        raise RuntimeError("Agent compatibility endpoints did not return capability metadata")
    if learning_launch.get("status") != "queued" or not learning_launch.get("plan_job_id") or not learning_launch.get("goal_id"):
        raise RuntimeError("Agent learning launch did not create a queued adaptive plan")
    if (not auto_launch.get("course_created") or repeat_auto_launch.get("course_created")
            or auto_launch.get("course_id") != repeat_auto_launch.get("course_id")
            or auto_course_workspace.get("course", {}).get("name") != "高等数学：极限的定义"):
        raise RuntimeError("automatic AI course creation did not derive and reuse the learning-topic course")
    if not memories or memories[0].get("id") != memory["id"]:
        raise RuntimeError("Agent Memory compatibility endpoint did not persist the confirmed memory")
    print(json.dumps({
        "status": "passed", "workspace": email, "course_id": course_id,
        "goal_id": goal["id"], "question_id": question["id"], "mistakes": len(mistakes),
        "reminders": len(reminders), "today_tasks": len(today["tasks"]),
        "rag_job_id": rag_job["job_id"], "ai_job_id": ai_job["job_id"],
        "resource_question_job_id": resource_question_job["job_id"],
        "agent_session_id": agent_session["id"],
        "auto_course_id": auto_launch["course_id"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SaaS smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
