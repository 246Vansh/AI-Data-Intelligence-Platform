from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def print_test(number, title):
    print("\n" + "=" * 60)
    print(f"TEST {number} — {title}")
    print("=" * 60)


def main():

    print("=" * 60)
    print("TESTING API ROBUSTNESS")
    print("=" * 60)

    # ========================================================
    # TEST 1 — Empty Question
    # ========================================================

    print_test(1, "Empty Question")

    response = client.post(
        "/api/analyze",
        json={"question": ""},
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 400
    assert response.json()["detail"] == "Question cannot be empty."

    print("RESULT: passed")

    # ========================================================
    # TEST 2 — Whitespace Question
    # ========================================================

    print_test(2, "Whitespace Question")

    response = client.post(
        "/api/analyze",
        json={"question": "   "},
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 400
    assert response.json()["detail"] == "Question cannot be empty."

    print("RESULT: passed")

    # ========================================================
    # TEST 3 — Missing Question Field
    # ========================================================

    print_test(3, "Missing Question Field")

    response = client.post(
        "/api/analyze",
        json={},
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 422

    print("RESULT: passed")

    # ========================================================
    # TEST 4 — Wrong Question Type
    # ========================================================

    print_test(4, "Wrong Question Type")

    response = client.post(
        "/api/analyze",
        json={"question": 12345},
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 422

    print("RESULT: passed")

    # ========================================================
    # TEST 5 — Null Question
    # ========================================================

    print_test(5, "Null Question")

    response = client.post(
        "/api/analyze",
        json={"question": None},
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 422

    print("RESULT: passed")

    # ========================================================
    # TEST 6 — Invalid HTTP Method
    # ========================================================

    print_test(6, "Invalid HTTP Method")

    response = client.get("/api/analyze")

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 405

    print("RESULT: passed")

    # ========================================================
    # TEST 7 — Unknown Endpoint
    # ========================================================

    print_test(7, "Unknown Endpoint")

    response = client.get("/api/does-not-exist")

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())

    assert response.status_code == 404

    print("RESULT: passed")

    # ========================================================
    # TEST 8 — Valid Analysis Response Contract
    # ========================================================

    print_test(8, "Valid Analysis Response Contract")

    response = client.post(
        "/api/analyze",
        json={"question": "Show me the top 5 stores by average weekly sales."},
    )

    print("STATUS:", response.status_code)

    assert response.status_code == 200

    body = response.json()

    required_fields = [
        "success",
        "question",
        "planner",
        "data",
        "insights",
        "insight_status",
        "insight_source",
        "insight_error",
        "visualization",
        "plan",
        "performance",
    ]

    for field in required_fields:
        assert field in body, f"Missing response field: {field}"

    assert body["success"] is True

    print("RESPONSE FIELDS:")
    print(list(body.keys()))

    print("RESULT: passed")

    # ========================================================
    # TEST 9 — Planner Response Contract
    # ========================================================

    print_test(9, "Planner Response Contract")

    planner = body["planner"]

    assert "type" in planner
    assert "fallback" in planner

    assert planner["type"] in {
        "fast",
        "claude",
    }

    assert isinstance(
        planner["fallback"],
        bool,
    )

    print("PLANNER:", planner)
    print("RESULT: passed")

    # ========================================================
    # TEST 10 — Analysis Data Contract
    # ========================================================

    print_test(10, "Analysis Data Contract")

    data = body["data"]

    assert "columns" in data
    assert "rows" in data
    assert "row_count" in data

    assert isinstance(data["columns"], list)
    assert isinstance(data["rows"], list)
    assert isinstance(data["row_count"], int)

    print("COLUMNS:", data["columns"])
    print("ROW COUNT:", data["row_count"])

    print("RESULT: passed")

    # ========================================================
    # TEST 11 — Plan Response Contract
    # ========================================================

    print_test(11, "Plan Response Contract")

    plan = body["plan"]

    required_plan_fields = [
        "filters",
        "group_by",
        "metric",
        "aggregation",
        "sort",
        "sort_by",
        "limit",
        "visualization",
        "time_granularity",
    ]

    for field in required_plan_fields:
        assert field in plan, f"Missing plan field: {field}"

    assert isinstance(plan["filters"], list)
    assert isinstance(plan["group_by"], list)

    print("PLAN:", plan)
    print("RESULT: passed")

    # ========================================================
    # TEST 12 — Visualization Response Contract
    # ========================================================

    print_test(12, "Visualization Response Contract")

    visualization = body["visualization"]

    assert "type" in visualization
    assert "title" in visualization
    assert "encoding" in visualization

    assert visualization["type"] in {
        "bar",
        "line",
        "pie",
        "scatter",
        "table",
    }

    print("VISUALIZATION:", visualization)
    print("RESULT: passed")

    # ========================================================
    # TEST 13 — Performance Response Contract
    # ========================================================

    print_test(13, "Performance Response Contract")

    performance = body["performance"]

    assert isinstance(performance, dict)
    assert "total" in performance

    assert isinstance(
        performance["total"],
        (int, float),
    )

    print("PERFORMANCE:", performance)
    print("RESULT: passed")

    # ========================================================
    # FINAL
    # ========================================================

    print("\n" + "=" * 60)
    print("ALL API ROBUSTNESS TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
