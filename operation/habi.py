# -*- coding: utf-8 -*-

import base64
import csv
import io
import json
import os
import random
import re
import tempfile
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import requests
from flask import Blueprint, Response, jsonify, render_template, request


habi_data_crawling_api = Blueprint(
    "habi_data_crawling_api",
    __name__,
    template_folder="/templates",
    static_folder="/static",
)

ocr_engine = None

COORDINATE_PATTERNS = [
    re.compile(r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"),
    re.compile(r"[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"),
    re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)"),
    re.compile(r"/(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)(?:[/?]|$)"),
]

ALLOWED_MAPS_HOSTS = (
    "google.com",
    "www.google.com",
    "maps.google.com",
    "maps.app.goo.gl",
    "goo.gl",
)

PHONE_PATTERN = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s().-]*)?(?:\d[\s().-]*){7,12}\d"
)

BULK_CSV_HEADERS = [
    "nombre",
    "descripcion",
    "telefono",
    "latitude",
    "longitude",
    "maps_url",
    "photo_url",
]

BULK_COMPLETE_LIMIT = 100
BULK_BATCH_LIMIT = 5000
BULK_BATCH_SIZE = 500
BULK_CHUNK_SIZE = 1000


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def env(name, default=None):
    return os.environ.get(name, default)


def extract_coordinates_from_maps_url(url):
    decoded_url = unquote(url)

    for pattern in COORDINATE_PATTERNS:
        match = pattern.search(decoded_url)

        if not match:
            continue

        latitude = float(match.group(1))
        longitude = float(match.group(2))

        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return {
                "latitude": latitude,
                "longitude": longitude,
            }

    return None


def is_allowed_maps_url(url):
    parsed_url = urlparse(url)
    hostname = parsed_url.hostname or ""

    return parsed_url.scheme in ("http", "https") and (
        hostname in ALLOWED_MAPS_HOSTS or hostname.endswith(".google.com")
    )


def get_ocr_engine():
    global ocr_engine

    if ocr_engine is None:
        os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

        from paddleocr import PaddleOCR

        ocr_engine = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )

    return ocr_engine


def run_ocr(ocr, image_path):
    if hasattr(ocr, "predict"):
        return ocr.predict(image_path)

    return ocr.ocr(
        image_path,
        cls=True,
    )


def collect_ocr_texts(ocr_result):
    texts = []

    def walk(value):
        if isinstance(value, str):
            texts.append(value)
            return

        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return

        if isinstance(value, (list, tuple)):
            if (
                len(value) >= 2
                and isinstance(value[1], (list, tuple))
                and value[1]
                and isinstance(value[1][0], str)
            ):
                texts.append(value[1][0])
                return

            for item in value:
                walk(item)

    walk(ocr_result)

    return texts


def normalize_phone(phone):
    has_plus = phone.strip().startswith("+")
    digits = re.sub(r"\D", "", phone)

    if len(digits) < 8 or len(digits) > 15:
        return None

    if has_plus:
        return f"+{digits}"

    return digits


def extract_phones_from_text(text):
    phones = []

    for match in PHONE_PATTERN.findall(text):
        phone = normalize_phone(match)

        if phone and phone not in phones:
            phones.append(phone)

        if len(phones) >= 5:
            break

    return phones


def get_storage_client():
    from google.cloud import storage

    return storage.Client()


def get_bigquery_client():
    from google.cloud import bigquery

    return bigquery.Client()


def get_publisher_client():
    from google.cloud import pubsub_v1

    return pubsub_v1.PublisherClient()


def upload_photo(photo, submission_id):
    bucket_name = env("IMAGE_BUCKET")

    if not bucket_name or not photo:
        return None

    extension = os.path.splitext(photo.filename or "")[1] or ".jpg"
    object_name = f"evidence/{submission_id}{extension}"
    bucket = get_storage_client().bucket(bucket_name)
    blob = bucket.blob(object_name)

    photo.stream.seek(0)
    blob.upload_from_file(
        photo.stream,
        content_type=photo.mimetype or "application/octet-stream",
    )

    return f"gs://{bucket_name}/{object_name}"


def upload_bulk_source(upload_id, filename, content, content_type):
    bucket_name = env("BULK_UPLOAD_BUCKET") or env("IMAGE_BUCKET")

    if not bucket_name:
        return None

    safe_filename = os.path.basename(filename or "bulk_upload.csv")
    object_name = f"bulk_uploads/{upload_id}/{safe_filename}"
    bucket = get_storage_client().bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_string(
        content,
        content_type=content_type or "application/octet-stream",
    )

    return f"gs://{bucket_name}/{object_name}"


def insert_bigquery_row(table_env_name, row):
    table_id = env(table_env_name)

    if not table_id:
        return

    errors = get_bigquery_client().insert_rows_json(
        table_id,
        [row],
    )

    if errors:
        raise RuntimeError(f"BigQuery insert failed: {errors}")


def publish_submission_event(event):
    topic = env("PUBSUB_TOPIC")

    if not topic:
        return None

    payload = json.dumps(event).encode("utf-8")
    future = get_publisher_client().publish(
        topic,
        payload,
        submission_id=event["submission_id"],
    )

    return future.result(timeout=30)


def build_bulk_csv_template():
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=BULK_CSV_HEADERS)
    writer.writeheader()
    writer.writerow({
        "nombre": "Ana Gomez",
        "descripcion": "Contacto cargado por archivo CSV",
        "telefono": "3001234567",
        "latitude": "4.710989",
        "longitude": "-74.072092",
        "maps_url": "",
        "photo_url": "gs://habi-form-aravel-344022-dev-images/evidence/demo.jpg",
    })
    writer.writerow({
        "nombre": "Carlos Perez",
        "descripcion": "Registro con coordenadas desde Google Maps",
        "telefono": "+573109876543",
        "latitude": "",
        "longitude": "",
        "maps_url": "https://www.google.com/maps/@4.6482837,-74.2478938,17z",
        "photo_url": "",
    })

    return output.getvalue()


def build_bulk_json_sample():
    return {
        "records": [
            {
                "nombre": "Ana Gomez",
                "descripcion": "Contacto cargado por JSON",
                "telefono": "3001234567",
                "latitude": 4.710989,
                "longitude": -74.072092,
                "maps_url": "",
                "photo_url": "gs://habi-form-aravel-344022-dev-images/evidence/demo.jpg",
            },
            {
                "nombre": "Carlos Perez",
                "descripcion": "Registro con URL de Google Maps",
                "telefono": "+573109876543",
                "latitude": "",
                "longitude": "",
                "maps_url": "https://www.google.com/maps/@4.6482837,-74.2478938,17z",
                "photo_url": "",
            },
        ]
    }


def parse_bulk_content(filename, raw_content):
    extension = os.path.splitext(filename or "")[1].lower()
    text = raw_content.decode("utf-8-sig")

    if extension == ".json":
        payload = json.loads(text)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            return payload["records"]
        raise ValueError("El JSON debe ser una lista o un objeto con records")

    if extension == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        missing_headers = [
            header for header in BULK_CSV_HEADERS if header not in (reader.fieldnames or [])
        ]
        if missing_headers:
            raise ValueError(
                f"Faltan columnas requeridas: {', '.join(missing_headers)}"
            )
        return list(reader)

    raise ValueError("El archivo debe ser .csv o .json")


def build_bulk_submission(record, upload_id, sequence):
    phone = normalize_phone(str(record.get("telefono") or ""))

    if not phone:
        raise ValueError("telefono invalido")

    latitude = parse_optional_float(record.get("latitude"))
    longitude = parse_optional_float(record.get("longitude"))
    maps_url = str(record.get("maps_url") or "").strip()

    if (latitude is None or longitude is None) and maps_url:
        coordinates = extract_coordinates_from_maps_url(maps_url)
        if coordinates:
            latitude = coordinates["latitude"]
            longitude = coordinates["longitude"]

    return {
        "submission_id": str(uuid.uuid4()),
        "created_at": utc_now_iso(),
        "nombre": clean_optional_string(record.get("nombre")),
        "descripcion": clean_optional_string(record.get("descripcion")),
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": None,
        "telefonos": [phone],
        "photo_name": None,
        "photo_url": clean_optional_string(record.get("photo_url")),
        "source": "bulk-upload",
        "bulk_upload_id": upload_id,
        "bulk_sequence": sequence,
    }


def clean_optional_string(value):
    if value in (None, ""):
        return None

    return str(value).strip() or None


def parse_optional_float(value):
    if value in (None, ""):
        return None

    return float(value)


def determine_bulk_strategy(record_count):
    if record_count <= BULK_COMPLETE_LIMIT:
        return {
            "mode": "complete",
            "unit_size": record_count,
            "estimated_units": 1 if record_count else 0,
        }

    if record_count <= BULK_BATCH_LIMIT:
        return {
            "mode": "batch",
            "unit_size": BULK_BATCH_SIZE,
            "estimated_units": (record_count + BULK_BATCH_SIZE - 1) // BULK_BATCH_SIZE,
        }

    return {
        "mode": "chunk",
        "unit_size": BULK_CHUNK_SIZE,
        "estimated_units": (record_count + BULK_CHUNK_SIZE - 1) // BULK_CHUNK_SIZE,
    }


def process_bulk_submissions(submissions):
    for submission in submissions:
        bigquery_row = {
            key: value
            for key, value in submission.items()
            if key not in ("bulk_upload_id", "bulk_sequence")
        }
        insert_bigquery_row("BQ_SUBMISSIONS_TABLE", bigquery_row)
        publish_submission_event(submission)

    return len(submissions)


def should_run_dataflow():
    return env("DATAFLOW_ENABLED", "false").lower() == "true"


def launch_dataflow_bulk_job(upload_id, source_url, source_format, strategy):
    template_path = env("DATAFLOW_TEMPLATE_GCS_PATH")

    if not template_path:
        raise RuntimeError("DATAFLOW_TEMPLATE_GCS_PATH no esta configurado")

    from google.auth import default
    from google.auth.transport.requests import Request

    project_id = env("DATAFLOW_PROJECT_ID") or env("GOOGLE_CLOUD_PROJECT")
    region = env("DATAFLOW_REGION", "us-central1")
    credentials, detected_project_id = default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project_id = project_id or detected_project_id
    credentials.refresh(Request())

    job_name = f"habi-bulk-{upload_id[:8]}"
    request_body = {
        "launchParameter": {
            "jobName": job_name,
            "containerSpecGcsPath": template_path,
            "parameters": {
                "input_file": source_url,
                "input_format": source_format,
                "pubsub_topic": env("PUBSUB_TOPIC", ""),
                "submissions_table": env("BQ_SUBMISSIONS_TABLE", ""),
                "upload_id": upload_id,
                "processing_mode": strategy["mode"],
                "unit_size": str(strategy["unit_size"]),
            },
            "environment": {
                "tempLocation": env("DATAFLOW_TEMP_LOCATION"),
                "stagingLocation": env("DATAFLOW_STAGING_LOCATION"),
                "serviceAccountEmail": env("DATAFLOW_SERVICE_ACCOUNT_EMAIL"),
            },
        }
    }

    response = requests.post(
        f"https://dataflow.googleapis.com/v1b3/projects/{project_id}/locations/{region}/flexTemplates:launch",
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
        json=request_body,
        timeout=30,
    )
    response.raise_for_status()

    return response.json().get("job", {}).get("id") or job_name


def build_bulk_upload_row(upload_id, source_url, filename, record_count, valid_count, invalid_count, strategy, status):
    return {
        "bulk_upload_id": upload_id,
        "created_at": utc_now_iso(),
        "source_file_url": source_url,
        "source_filename": filename,
        "record_count": record_count,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "processing_mode": strategy["mode"],
        "unit_size": strategy["unit_size"],
        "estimated_units": strategy["estimated_units"],
        "status": status,
    }


def build_submission(form, photo):
    submission_id = str(uuid.uuid4())
    telefonos = [
        telefono.strip()
        for telefono in form.getlist("telefonos")
        if telefono.strip()
    ][:5]

    return {
        "submission_id": submission_id,
        "created_at": utc_now_iso(),
        "nombre": form.get("nombre"),
        "descripcion": form.get("descripcion"),
        "latitude": parse_float(form.get("latitude")),
        "longitude": parse_float(form.get("longitude")),
        "accuracy": parse_float(form.get("accuracy")),
        "telefonos": telefonos,
        "photo_name": photo.filename if photo else None,
        "photo_url": None,
        "source": "habi-form",
    }


def parse_float(value):
    if value in (None, ""):
        return None

    return float(value)


def build_fake_call_result(event):
    phones = event.get("telefonos") or []
    successful = bool(phones) and random.random() >= 0.2
    scheduled_visit = successful and random.random() >= 0.45

    if successful and scheduled_visit:
        response = "Cliente contesto y agendo visita."
        next_action = "confirm_visit"
    elif successful:
        response = "Cliente contesto, pero pidio llamada posterior."
        next_action = "call_later"
    else:
        response = "No fue posible contactar al cliente."
        next_action = "retry"

    return {
        "call_id": str(uuid.uuid4()),
        "submission_id": event["submission_id"],
        "created_at": utc_now_iso(),
        "status": "successful" if successful else "failed",
        "attempt_number": 1,
        "phone_numbers": phones,
        "selected_phone": phones[0] if phones else None,
        "response": response,
        "scheduled_visit": scheduled_visit,
        "next_action": next_action,
        "raw_event": json.dumps(event),
    }


def decode_pubsub_message(payload):
    message = payload.get("message", {})
    data = message.get("data")

    if not data:
        return {}

    return json.loads(
        base64.b64decode(data).decode("utf-8")
    )


@habi_data_crawling_api.route("/home", methods=["GET", "POST"])
def home():
    return render_template("home.html")


@habi_data_crawling_api.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@habi_data_crawling_api.route("/extract_maps_coordinates", methods=["POST"])
def extract_maps_coordinates():
    payload = request.get_json(silent=True) or {}
    maps_url = (payload.get("url") or "").strip()

    if not maps_url:
        return jsonify({
            "message": "Debe enviar una URL de Google Maps",
        }), 400

    if not is_allowed_maps_url(maps_url):
        return jsonify({
            "message": "La URL debe pertenecer a Google Maps",
        }), 400

    coordinates = extract_coordinates_from_maps_url(maps_url)

    if not coordinates:
        try:
            response = requests.get(
                maps_url,
                allow_redirects=True,
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            coordinates = extract_coordinates_from_maps_url(response.url)

        except requests.RequestException:
            coordinates = None

    if not coordinates:
        return jsonify({
            "message": "No fue posible extraer latitud y longitud",
        }), 422

    return jsonify(coordinates), 200


@habi_data_crawling_api.route("/detect_phones", methods=["POST"])
def detect_phones():
    photo = request.files.get("photo")

    if not photo:
        return jsonify({
            "message": "Debe enviar una imagen",
        }), 400

    suffix = os.path.splitext(photo.filename or "")[1] or ".jpg"
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            photo.save(temp_file)
            temp_path = temp_file.name

        ocr = get_ocr_engine()
        ocr_result = run_ocr(
            ocr,
            temp_path,
        )
        text = " ".join(
            collect_ocr_texts(ocr_result)
        )
        phones = extract_phones_from_text(text)

        return jsonify({"phones": phones}), 200

    except ImportError:
        return jsonify({
            "message": "PaddleOCR no esta instalado en el entorno",
        }), 500

    except Exception as error:
        print("Error detectando telefonos:", error)

        return jsonify({
            "message": "No fue posible analizar la imagen",
        }), 500

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@habi_data_crawling_api.route("/save_crawling", methods=["POST"])
def save_crawling():
    photo = request.files.get("photo")
    submission = build_submission(request.form, photo)
    submission["photo_url"] = upload_photo(
        photo,
        submission["submission_id"],
    )

    insert_bigquery_row(
        "BQ_SUBMISSIONS_TABLE",
        submission,
    )
    publish_submission_event(submission)

    return jsonify({
        "message": "Formulario recibido correctamente",
        **submission,
    }), 200


@habi_data_crawling_api.route("/bulk_phone_template.csv", methods=["GET"])
def bulk_phone_template():
    return Response(
        build_bulk_csv_template(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=habi_bulk_phone_template.csv"
        },
    )


@habi_data_crawling_api.route("/bulk_phone_sample.json", methods=["GET"])
def bulk_phone_sample():
    return jsonify(build_bulk_json_sample()), 200


@habi_data_crawling_api.route("/bulk_phone_upload", methods=["POST"])
def bulk_phone_upload():
    upload = request.files.get("bulk_file")

    if not upload:
        return jsonify({
            "message": "Debe adjuntar un archivo CSV o JSON",
        }), 400

    upload_id = str(uuid.uuid4())
    raw_content = upload.read()
    source_format = os.path.splitext(upload.filename or "")[1].lower().replace(".", "")

    try:
        raw_records = parse_bulk_content(upload.filename, raw_content)
        submissions = []
        errors = []

        for index, record in enumerate(raw_records, start=1):
            try:
                submissions.append(
                    build_bulk_submission(record, upload_id, index)
                )
            except Exception as error:
                errors.append({
                    "row": index,
                    "message": str(error),
                })

        if not submissions:
            return jsonify({
                "message": "El archivo no tiene registros validos",
                "errors": errors[:20],
            }), 422

        strategy = determine_bulk_strategy(len(submissions))
        source_url = upload_bulk_source(
            upload_id,
            upload.filename,
            raw_content,
            upload.mimetype,
        )

        status = "queued_dataflow" if should_run_dataflow() else "processed_dev_fallback"
        bulk_row = build_bulk_upload_row(
            upload_id,
            source_url,
            upload.filename,
            len(raw_records),
            len(submissions),
            len(errors),
            strategy,
            status,
        )
        insert_bigquery_row("BQ_BULK_UPLOADS_TABLE", bulk_row)

        dataflow_job_id = None
        published_count = 0

        if should_run_dataflow():
            dataflow_job_id = launch_dataflow_bulk_job(
                upload_id,
                source_url,
                source_format,
                strategy,
            )
        else:
            published_count = process_bulk_submissions(submissions)

        return jsonify({
            "message": "Cargue masivo recibido",
            "bulk_upload_id": upload_id,
            "source_file_url": source_url,
            "record_count": len(raw_records),
            "valid_count": len(submissions),
            "invalid_count": len(errors),
            "strategy": strategy,
            "dataflow_enabled": should_run_dataflow(),
            "dataflow_job_id": dataflow_job_id,
            "published_count": published_count,
            "errors": errors[:20],
        }), 200

    except ValueError as error:
        return jsonify({
            "message": str(error),
        }), 400


@habi_data_crawling_api.route("/process_call", methods=["POST"])
def process_call():
    payload = request.get_json(silent=True) or {}
    event = decode_pubsub_message(payload) if "message" in payload else payload

    if not event.get("submission_id"):
        return jsonify({
            "message": "Evento sin submission_id",
        }), 400

    call_result = build_fake_call_result(event)

    insert_bigquery_row(
        "BQ_CALL_ATTEMPTS_TABLE",
        call_result,
    )

    return jsonify({
        "message": "Llamada fake procesada",
        **call_result,
    }), 200
