from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def print_section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():

    print("=" * 60)
    print("TESTING API")
    print("=" * 60)

    # ========================================================
    # TEST 1 — Root
    # ========================================================

    print_section("TEST 1 — Root Endpoint")

    response = client.get("/")

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 200

    body = response.json()

    assert body["project"] == "AI Data Intelligence Platform"
    assert body["status"] == "running"

    print("RESULT: passed")

    # ========================================================
    # TEST 2 — Dataset Preview
    # ========================================================

    print_section("TEST 2 — Dataset Preview")

    response = client.get("/api/dataset/preview")

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 200

    body = response.json()

    assert "columns" in body
    assert "rows" in body

    assert len(body["rows"]) <= 10

    print("COLUMNS:", body["columns"])
    print("ROWS:", len(body["rows"]))
    print("RESULT: passed")

    # ========================================================
    # TEST 3 — Dataset Metadata
    # ========================================================

    print_section("TEST 3 — Dataset Metadata")

    response = client.get("/api/dataset/metadata")

    print("STATUS:", response.status_code)

    assert response.status_code == 200

    metadata = response.json()

    print("METADATA TYPE:", type(metadata).__name__)

    assert metadata is not None

    print("RESULT: passed")

    # ========================================================
    # TEST 4 — Dataset Profile
    # ========================================================

    print_section("TEST 4 — Dataset Profile")

    response = client.get("/api/dataset/profile")

    print("STATUS:", response.status_code)

    assert response.status_code == 200

    profile = response.json()

    print("PROFILE TYPE:", type(profile).__name__)

    assert profile is not None

    print("RESULT: passed")

    # ========================================================
    # TEST 5 — Empty Question
    # ========================================================

    print_section("TEST 5 — Empty Question")

    response = client.post(
        "/api/analyze",
        json={"question": ""},
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 400

    print("RESULT: passed")

    # ========================================================
    # TEST 6 — Valid Analysis
    # ========================================================

    print_section("TEST 6 — Valid Analysis")

    response = client.post(
        "/api/analyze",
        json={"question": "Show me the top 5 stores by average weekly sales."},
    )

    print("STATUS:", response.status_code)

    assert response.status_code == 200

    result = response.json()

    print("SUCCESS:", result.get("success"))
    print("PLANNER:", result.get("planner"))
    print("DATA ROWS:", result.get("data", {}).get("row_count"))
    print("INSIGHT STATUS:", result.get("insight_status"))
    print("VISUALIZATION:", result.get("visualization", {}).get("type"))

    assert result["success"] is True

    assert "planner" in result
    assert "data" in result
    assert "plan" in result
    assert "visualization" in result
    assert "performance" in result

    assert result["data"]["row_count"] == 5

    print("RESULT: passed")

    # ========================================================
    # TEST 7 — Holiday Analysis / AI Fallback
    # ========================================================

    print_section("TEST 7 — AI Fallback Analysis")

    response = client.post(
        "/api/analyze",
        json={
            "question": (
                "Show me the top 5 stores by average weekly sales during holidays."
            )
        },
    )

    print("STATUS:", response.status_code)

    assert response.status_code == 200

    result = response.json()

    print("PLANNER:", result["planner"])
    print("PLAN:", result["plan"])
    print("DATA ROWS:", result["data"]["row_count"])

    assert result["success"] is True
    assert result["data"]["row_count"] == 5

    print("RESULT: passed")

    # ========================================================
    # FINAL
    # ========================================================

    print("\n" + "=" * 60)
    print("ALL API TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
