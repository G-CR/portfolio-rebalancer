from decimal import Decimal


async def test_list_asset_classes_returns_seeded_defaults(api_client) -> None:
    response = await api_client.get("/api/asset-classes")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": item["id"],
            "name": expected_name,
            "target_weight": expected_weight,
            "display_order": expected_order,
            "notes": None,
            "is_active": True,
        }
        for item, (expected_name, expected_weight, expected_order) in zip(
            response.json(),
            (
                ("红利低波", "0.20000000", 1),
                ("红利质量", "0.20000000", 2),
                ("标普 500", "0.30000000", 3),
                ("纳斯达克 100", "0.20000000", 4),
                ("黄金", "0.10000000", 5),
            ),
            strict=True,
        )
    ]


async def test_asset_class_update_rejects_total_other_than_one(api_client) -> None:
    classes = (await api_client.get("/api/asset-classes")).json()
    payload = [{**item, "target_weight": "0.10000000"} for item in classes]

    response = await api_client.put("/api/asset-classes", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TARGET_WEIGHT_TOTAL_INVALID"
    assert response.json()["detail"]["actual_total"] == "0.50000000"

    after = (await api_client.get("/api/asset-classes")).json()
    assert after == classes


async def test_asset_class_update_replaces_all_rows(api_client) -> None:
    classes = (await api_client.get("/api/asset-classes")).json()
    payload = [
        {
            **classes[0],
            "target_weight": "0.25000000",
            "display_order": 2,
            "notes": "红利策略核心仓位",
        },
        {
            **classes[1],
            "target_weight": "0.15000000",
            "display_order": 1,
            "notes": "质量因子补充",
        },
        {
            **classes[2],
            "target_weight": "0.25000000",
            "display_order": 3,
            "notes": "美股宽基",
        },
        {
            **classes[3],
            "target_weight": "0.25000000",
            "display_order": 4,
            "notes": "成长风格",
        },
        {
            **classes[4],
            "target_weight": "0.10000000",
            "display_order": 5,
            "notes": "对冲仓位",
        },
    ]

    response = await api_client.put("/api/asset-classes", json=payload)

    assert response.status_code == 200
    assert [item["display_order"] for item in response.json()] == [1, 2, 3, 4, 5]
    assert [
        (item["name"], item["target_weight"], item["notes"])
        for item in response.json()
    ] == [
        ("红利质量", "0.15000000", "质量因子补充"),
        ("红利低波", "0.25000000", "红利策略核心仓位"),
        ("标普 500", "0.25000000", "美股宽基"),
        ("纳斯达克 100", "0.25000000", "成长风格"),
        ("黄金", "0.10000000", "对冲仓位"),
    ]
    assert sum(Decimal(item["target_weight"]) for item in response.json()) == Decimal("1")

    listed = (await api_client.get("/api/asset-classes")).json()
    assert listed == response.json()
