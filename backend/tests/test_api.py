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


def _sse_data(line: str) -> str:
    """The payload of one SSE line.

    Exactly one space after "data:" is protocol framing; any further whitespace is
    content. Stripping it all glues streamed tokens together into one long word.
    """
    payload = line[5:]
    return payload[1:] if payload.startswith(" ") else payload


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


def test_chat_answers_only_from_the_material(client: httpx.Client) -> None:
    """Invariant I2, over the wire. A tutor that answers a question the material does not
    cover is worse than one that declines: the student cannot tell which answers came from
    their slides and which the model invented."""
    _db_or_skip(client)
    courses = client.get("/api/courses").json()
    if not courses:
        pytest.skip("no ingested course")

    with client.stream(
        "POST",
        f"/api/courses/{courses[0]['id']}/chat",
        json={"message": "Who won the 2022 FIFA World Cup?"},
        timeout=180,
    ) as response:
        assert response.status_code == 200
        body = "".join(
            _sse_data(line)
            for line in response.iter_lines()
            if line.startswith("data:") and not _sse_data(line).lstrip().startswith("[")
        ).lower()

    assert body.strip(), "the tutor must say something"
    declined = any(
        phrase in body
        for phrase in (
            "no information",
            "not mention",
            "no mention",
            "do not cover",
            "does not cover",
            "can't help",
            "cannot help",
        )
    )
    assert declined, f"expected a refusal grounded in the passages, got: {body[:200]}"
    assert "argentina" not in body, "answered from world knowledge instead of the material"


def test_chat_cites_the_passages_it_used(client: httpx.Client) -> None:
    """I1: the passages arrive before the answer, so a claim can be traced the moment it
    appears rather than after the fact."""
    _db_or_skip(client)
    courses = client.get("/api/courses").json()
    if not courses:
        pytest.skip("no ingested course")

    import json as _json

    sources = None
    with client.stream(
        "POST",
        f"/api/courses/{courses[0]['id']}/chat",
        json={"message": "What is vertical fragmentation?"},
        timeout=180,
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                payload = _sse_data(line).lstrip()
                if payload.startswith("["):
                    sources = _json.loads(payload)
                    break

    assert sources, "the answer must arrive with the passages it was built from"
    for source in sources:
        assert source["page_start"] >= 1
        assert source["document_name"]
        assert source["page_end"] >= source["page_start"]


def test_upload_returns_an_id_the_client_can_poll(client: httpx.Client) -> None:
    """The upload used to return a freshly minted UUID matching no row, so every status
    request 404'd and the interface could not tell a student whether ingestion had
    finished — it just looked stuck forever."""
    _db_or_skip(client)
    from io import BytesIO

    from pptx import Presentation

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Upload Probe"
    slide.placeholders[1].text = "A short passage about an entirely invented subject."
    buffer = BytesIO()
    presentation.save(buffer)

    course = client.post("/api/courses", json={"name": f"upload-probe-{uuid.uuid4()}"}).json()
    response = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("probe.pptx", buffer.getvalue(),
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert response.status_code == 202
    document = response.json()

    # The student's own filename, not the temp name it was staged under.
    assert document["filename"] == "probe.pptx"

    status = client.get(f"/api/documents/{document['id']}/status")
    assert status.status_code == 200, "the returned id must address a real document"
    assert status.json()["filename"] == "probe.pptx"


def test_a_new_course_starts_empty_and_isolated(client: httpx.Client) -> None:
    """Material added to one course must not leak into another — otherwise 'answers from
    your material' means 'answers from anyone's material'."""
    _db_or_skip(client)
    course = client.post("/api/courses", json={"name": f"isolation-probe-{uuid.uuid4()}"}).json()
    assert course["chunk_count"] == 0
    assert client.get(f"/api/courses/{course['id']}/topics").json() == []
    assert client.get(f"/api/courses/{course['id']}/quizzes").json() == []
