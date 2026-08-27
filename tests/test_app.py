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
    monkeypatch.delenv("BQ_BULK_UPLOADS_TABLE", raising=False)
    monkeypatch.delenv("PUBSUB_TOPIC", raising=False)
    monkeypatch.delenv("DATAFLOW_ENABLED", raising=False)
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


def test_bulk_template_download(client):
    response = client.get("/habi/data_crawling/bulk_phone_template.csv")

    assert response.status_code == 200
    assert "nombre,descripcion,telefono,latitude,longitude,maps_url,photo_url" in response.text


def test_bulk_upload_csv_processes_valid_rows(client, monkeypatch):
    inserted = []
    published = []
    csv_content = (
        "nombre,descripcion,telefono,latitude,longitude,maps_url,photo_url\n"
        "Ana,Demo,300 123 4567,4.7,-74.0,,gs://bucket/demo.jpg\n"
        "Bad,Demo,123,,,,\n"
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
    monkeypatch.setattr(
        habi,
        "upload_bulk_source",
        lambda *_args: "gs://bucket/bulk_uploads/source.csv",
    )

    response = client.post(
        "/habi/data_crawling/bulk_phone_upload",
        data={
            "bulk_file": (
                BytesIO(csv_content.encode("utf-8")),
                "contacts.csv",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["valid_count"] == 1
    assert response.json["invalid_count"] == 1
    assert response.json["strategy"]["mode"] == "complete"
    assert response.json["published_count"] == 1
    assert inserted[0][0] == "BQ_BULK_UPLOADS_TABLE"
    assert inserted[1][0] == "BQ_SUBMISSIONS_TABLE"
    assert published[0]["telefonos"] == ["3001234567"]


def test_bulk_upload_json_accepts_records_object(client, monkeypatch):
    monkeypatch.setattr(habi, "insert_bigquery_row", lambda *_args: None)
    monkeypatch.setattr(habi, "publish_submission_event", lambda _event: "message-id")
    monkeypatch.setattr(habi, "upload_bulk_source", lambda *_args: None)

    response = client.post(
        "/habi/data_crawling/bulk_phone_upload",
        data={
            "bulk_file": (
                BytesIO(json.dumps({
                    "records": [
                        {
                            "nombre": "Ana",
                            "telefono": "+57 310 987 6543",
                            "maps_url": "https://www.google.com/maps/@4.6482837,-74.2478938,17z",
                        }
                    ]
                }).encode("utf-8")),
                "contacts.json",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["valid_count"] == 1
