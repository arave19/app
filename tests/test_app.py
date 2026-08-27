import base64
import json
from io import BytesIO

import pytest

from main import app
from operation import habi


@pytest.fixture()
def client(monkeypatch):
    app.config.update(TESTING=True)
    monkeypatch.delenv("IMAGE_BUCKET", raising=False)
    monkeypatch.delenv("BQ_SUBMISSIONS_TABLE", raising=False)
    monkeypatch.delenv("BQ_CALL_ATTEMPTS_TABLE", raising=False)
    monkeypatch.delenv("PUBSUB_TOPIC", raising=False)
    return app.test_client()


def test_health(client):
    response = client.get("/habi/data_crawling/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_extract_phones_from_text():
    phones = habi.extract_phones_from_text(
        "Tel 300 123 4567 fijo (601) 234-5678 WhatsApp +57 310 987 6543"
    )

    assert phones == [
        "3001234567",
        "6012345678",
        "+573109876543",
    ]


def test_detect_phones_uses_ocr_without_submit(client, monkeypatch):
    monkeypatch.setattr(habi, "get_ocr_engine", lambda: object())
    monkeypatch.setattr(
        habi,
        "run_ocr",
        lambda _ocr, _path: [{"rec_texts": ["Llamar al 300 123 4567"]}],
    )

    response = client.post(
        "/habi/data_crawling/detect_phones",
        data={"photo": (BytesIO(b"fake-image"), "evidence.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json == {"phones": ["3001234567"]}


def test_save_crawling_persists_and_publishes(client, monkeypatch):
    inserted = []
    published = []

    monkeypatch.setattr(
        habi,
        "upload_photo",
        lambda _photo, submission_id: f"gs://bucket/evidence/{submission_id}.jpg",
    )
    monkeypatch.setattr(
        habi,
        "insert_bigquery_row",
        lambda table_env_name, row: inserted.append((table_env_name, row)),
    )
    monkeypatch.setattr(
        habi,
        "publish_submission_event",
        lambda event: published.append(event) or "message-id",
    )

    response = client.post(
        "/habi/data_crawling/save_crawling",
        data={
            "nombre": "Ana",
            "descripcion": "Registro",
            "latitude": "4.710989",
            "longitude": "-74.072092",
            "accuracy": "25",
            "telefonos": ["3001234567", "", "+573109876543"],
            "photo": (BytesIO(b"fake-image"), "evidence.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["telefonos"] == ["3001234567", "+573109876543"]
    assert response.json["photo_url"].startswith("gs://bucket/evidence/")
    assert inserted[0][0] == "BQ_SUBMISSIONS_TABLE"
    assert published[0]["submission_id"] == response.json["submission_id"]


def test_process_call_accepts_pubsub_payload(client, monkeypatch):
    inserted = []
    event = {
        "submission_id": "submission-1",
        "telefonos": ["3001234567"],
    }
    payload = {
        "message": {
            "data": base64.b64encode(
                json.dumps(event).encode("utf-8")
            ).decode("utf-8")
        }
    }

    monkeypatch.setattr(
        habi,
        "insert_bigquery_row",
        lambda table_env_name, row: inserted.append((table_env_name, row)),
    )
    monkeypatch.setattr(habi.random, "random", lambda: 0.9)

    response = client.post(
        "/habi/data_crawling/process_call",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json["status"] == "successful"
    assert response.json["scheduled_visit"] is True
    assert inserted[0][0] == "BQ_CALL_ATTEMPTS_TABLE"
