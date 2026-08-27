import csv
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions


PHONE_PATTERN = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s().-]*)?(?:\d[\s().-]*){7,12}\d"
)

COORDINATE_PATTERNS = [
    re.compile(r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"),
    re.compile(r"[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"),
    re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)"),
    re.compile(r"/(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)(?:[/?]|$)"),
]


class BulkOptions(PipelineOptions):
    @classmethod
    def _add_argparse_args(cls, parser):
        parser.add_argument("--input_file", required=True)
        parser.add_argument("--input_format", required=True, choices=["csv", "json"])
        parser.add_argument("--pubsub_topic", required=True)
        parser.add_argument("--submissions_table", required=True)
        parser.add_argument("--upload_id", required=True)
        parser.add_argument("--processing_mode", default="complete")
        parser.add_argument("--unit_size", default="100")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_phone(phone):
    has_plus = phone.strip().startswith("+")
    digits = re.sub(r"\D", "", phone)

    if len(digits) < 8 or len(digits) > 15:
        return None

    if has_plus:
        return f"+{digits}"

    return digits


def parse_optional_float(value):
    if value in (None, ""):
        return None

    return float(value)


def clean_optional_string(value):
    if value in (None, ""):
        return None

    return str(value).strip() or None


def extract_coordinates_from_maps_url(url):
    decoded_url = unquote(url or "")

    for pattern in COORDINATE_PATTERNS:
        match = pattern.search(decoded_url)

        if not match:
            continue

        latitude = float(match.group(1))
        longitude = float(match.group(2))

        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude

    return None, None


def parse_csv_line(header):
    def _parse(line):
        reader = csv.DictReader([header, line])
        return next(reader)

    return _parse


def parse_json_records(text):
    payload = json.loads(text)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return payload["records"]

    raise ValueError("JSON must be a list or an object with records")


def build_submission(record, upload_id):
    phone = normalize_phone(str(record.get("telefono") or ""))

    if not phone:
        return None

    latitude = parse_optional_float(record.get("latitude"))
    longitude = parse_optional_float(record.get("longitude"))

    if (latitude is None or longitude is None) and record.get("maps_url"):
        latitude, longitude = extract_coordinates_from_maps_url(record.get("maps_url"))

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
        "source": "bulk-upload-dataflow",
        "bulk_upload_id": upload_id,
    }


def to_pubsub_bytes(record):
    return json.dumps(record).encode("utf-8")


def remove_internal_fields(record):
    clean = dict(record)
    clean.pop("bulk_upload_id", None)
    return clean


def run():
    options = PipelineOptions()
    bulk_options = options.view_as(BulkOptions)

    with beam.Pipeline(options=options) as pipeline:
        lines = pipeline | "Read source file" >> beam.io.ReadFromText(
            bulk_options.input_file
        )

        if bulk_options.input_format == "csv":
            header = (
                lines
                | "Read header" >> beam.combiners.Sample.FixedSizeGlobally(1)
                | "Flatten header" >> beam.FlatMap(lambda rows: rows)
            )
            records = (
                lines
                | "Skip CSV header" >> beam.Filter(
                    lambda line, h: line != h,
                    beam.pvalue.AsSingleton(header),
                )
                | "Parse CSV" >> beam.Map(
                    lambda line, h: parse_csv_line(h)(line),
                    beam.pvalue.AsSingleton(header),
                )
            )
        else:
            records = (
                lines
                | "Join JSON file" >> beam.CombineGlobally("\n".join)
                | "Parse JSON records" >> beam.FlatMap(parse_json_records)
            )

        submissions = (
            records
            | "Build submission" >> beam.Map(
                lambda record: build_submission(record, bulk_options.upload_id)
            )
            | "Only valid submissions" >> beam.Filter(lambda record: record is not None)
        )

        (
            submissions
            | "Prepare BigQuery rows" >> beam.Map(remove_internal_fields)
            | "Write submissions to BigQuery" >> beam.io.WriteToBigQuery(
                bulk_options.submissions_table,
                write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
            )
        )

        (
            submissions
            | "Encode PubSub events" >> beam.Map(to_pubsub_bytes)
            | "Publish fake call messages" >> beam.io.WriteToPubSub(
                bulk_options.pubsub_topic
            )
        )


if __name__ == "__main__":
    run()
