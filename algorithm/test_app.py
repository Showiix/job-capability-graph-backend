from fastapi.testclient import TestClient

from app import app


def test_graph_match_uses_required_weights_and_mastery_threshold() -> None:
    response = TestClient(app).post(
        "/match",
        json={
            "job_id": "dynamic-job",
            "job": {
                "job_name": "AI 工程师",
                "required_skills": [
                    {"skill": "Python", "weight": 1.0},
                    {"skill": "RAG", "weight": 0.5},
                ],
                "bonus_skills": ["Docker"],
            },
            "resume": {
                "skills": [
                    {"skill": "Python", "mastery": "familiar"},
                    {"skill": "RAG", "mastery": "aware"},
                    {"skill": "Docker", "mastery": "proficient"},
                ]
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["match_score"] == 1 / 1.5
    assert data["required"]["satisfied"] == ["Python"]
    assert data["required"]["missing"] == ["RAG"]
    assert data["bonus"]["hit"] == ["Docker"]
