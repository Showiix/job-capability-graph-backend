from app.discovery.emerging_router import load_emerging_jobs


def test_emerging_job_snapshot_is_present_and_structured() -> None:
    value = load_emerging_jobs()

    assert value["summary"]["definitionCount"] == len(value["jobs"])
    assert value["jobs"][0]["title"]
    assert value["jobs"][0]["reviewStatusCode"] in {"pending", "approved", "rejected"}
