from app.discovery.evolution_router import load_evolution_data


def test_evolution_delivery_contains_all_changes() -> None:
    value = load_evolution_data()

    assert len(value["jobs"]) == 524
    assert sum(len(job["changes"]) for job in value["jobs"]) == 4007
    assert all(
        change.get("evidence") for job in value["jobs"] for change in job["changes"]
    )


async def test_evolution_api_filters_and_pages(client) -> None:
    response = await client.get(
        "/api/v1/capability-evolution",
        params={"change_type": "AI技能新增", "confidence": "高", "page_size": 5},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] > 0
    assert len(data["items"]) == 5
    assert all(item["change_type"] == "AI技能新增" for item in data["items"])
    assert all(item["confidence"] == "高" for item in data["items"])
