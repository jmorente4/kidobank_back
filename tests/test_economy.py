def test_politica_inflacion_padre(client, padre_user):
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    unconfigured_res = client.get("/api/v1/economy/inflation", headers=headers)
    assert unconfigured_res.status_code == 200
    assert unconfigured_res.json() is None

    create_res = client.post(
        "/api/v1/economy/inflation",
        json={"nombre": "Inflación familiar", "tasa_semanal": 0.02},
        headers=headers,
    )
    assert create_res.status_code == 201
    body = create_res.json()
    assert body["tasa_semanal"] == 0.02
    assert body["estado"] == "ACTIVA"

    get_res = client.get("/api/v1/economy/inflation", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["tasa_semanal"] == 0.02
