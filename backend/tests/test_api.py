"""API tests (spec §12). The leak boundary and the core answer payload."""

import uuid

import httpx
import pytest

BASE = "http://localhost:8000"


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    """Exercise the running service rather than an in-process app.

    `TestClient` drives the app through its own anyio portal, which collides with the
    engine-disposal fixture the same way I-026 did — asyncpg pools bind to the loop that
    created them. Testing over HTTP avoids that entirely and has the merit of exercising
    the surface that is actually deployed. Skips when the server is not up, so CI stays
    service-free.
    """
    return httpx.Client(base_url=BASE, timeout=30)


def _db_or_skip(client: httpx.Client) -> None:
    try:
        if client.get("/api/health").status_code != 200:
            pytest.skip("api not healthy")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"api not running at {BASE}: {exc}")


def test_served_quiz_never_contains_an_answer(client: httpx.Client) -> None:
    """I-010, asserted on the wire rather than on the serializer. Correctness lives in a
    JSON blob with no separate column, so this is the one boundary that keeps it out."""
    _db_or_skip(client)
    courses = client.get("/api/courses").json()
    if not courses:
        pytest.skip("no ingested course")
    quizzes = client.get(f"/api/courses/{courses[0]['id']}/quizzes").json()
    if not quizzes:
        pytest.skip("no generated quiz")

    raw = client.get(f"/api/quizzes/{quizzes[0]['id']}").text
    assert "is_correct" not in raw
    assert "why_wrong" not in raw

    body = client.get(f"/api/quizzes/{quizzes[0]['id']}").json()
    assert body["questions"], "a quiz must serve its questions"
    for question in body["questions"]:
        for option in question["options"]:
            assert set(option) == {"id", "text"}


def test_wrong_answer_returns_everything_the_panel_needs(client: httpx.Client) -> None:
    """§12: the answer-submission response is the product's core moment and must render
    the explanation with zero further round trips."""
    _db_or_skip(client)
    courses = client.get("/api/courses").json()
    if not courses:
        pytest.skip("no ingested course")
    quizzes = client.get(f"/api/courses/{courses[0]['id']}/quizzes").json()
    if not quizzes:
        pytest.skip("no generated quiz")
    quiz = client.get(f"/api/quizzes/{quizzes[0]['id']}").json()

    attempt = client.post("/api/attempts", json={"quiz_id": quiz["id"]}).json()
    question = quiz["questions"][0]
    # Answer every option; at least one is wrong, and that is the path that matters.
    wrong_payload = None
    for option in question["options"]:
        body = client.post(
            f"/api/attempts/{attempt['id']}/answers",
            json={"question_id": question["id"], "selected_option_id": option["id"]},
        ).json()
        if not body["is_correct"]:
            wrong_payload = body
            break

    assert wrong_payload is not None, "a four-option question must have a wrong answer"
    assert wrong_payload["correct_option_id"] in {"A", "B", "C", "D"}
    assert wrong_payload["why_wrong"], "the wrong-answer moment needs its rationale"
    assert wrong_payload["explanation"]
    source = wrong_payload["source"]
    assert source is not None, "I1: a wrong answer must cite its source"
    assert source["page"] >= 1
    assert source["document_name"]
    assert source["text"].strip()


def test_unsupported_upload_is_rejected_with_a_useful_message(client: httpx.Client) -> None:
    _db_or_skip(client)
    courses = client.get("/api/courses").json()
    if not courses:
        pytest.skip("no ingested course")
    response = client.post(
        f"/api/courses/{courses[0]['id']}/documents",
        files={"file": ("notes.docx", b"stub", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert ".pptx" in response.json()["detail"]


def test_missing_resources_are_404_not_500(client: httpx.Client) -> None:
    _db_or_skip(client)
    missing = uuid.uuid4()
    assert client.get(f"/api/quizzes/{missing}").status_code == 404
    assert client.get(f"/api/jobs/{missing}").status_code == 404
