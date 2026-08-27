# -*- coding: utf-8 -*-

import base64
import json
import os
import random
import re
import tempfile
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import requests
from flask import Blueprint, jsonify, render_template, request


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
