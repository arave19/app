# Habi Form App

Flask application for:

- Evidence form UI.
- Google Maps URL coordinate extraction.
- Phone OCR detection with PaddleOCR before submit.
- Photo upload to Cloud Storage.
- Form persistence to BigQuery.
- Submission event publication to Pub/Sub.
- Fake call worker endpoint for Pub/Sub push.
- Bulk phone upload from CSV or JSON.
- Dataflow-ready Beam pipeline for bulk processing.

## Local

```powershell
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
set FLASK_APP=main
flask run
```

Open:

```text
http://127.0.0.1:5000/habi/data_crawling/home
```

## Tests

```powershell
pytest -q
```

## Docker

```powershell
docker build -t habi-form-app:local .
docker run --rm -p 8080:8080 habi-form-app:local
```

## Cloud Build

```powershell
gcloud builds submit . --config cloudbuild.yaml --project aravel-344022 --substitutions _REGION=us-central1,_AR_REPOSITORY=habi,_IMAGE_NAME=habi-form-app,_IMAGE_TAG=dev
```

## Runtime Environment

The Cloud Run app service uses:

- `IMAGE_BUCKET`
- `BQ_SUBMISSIONS_TABLE`
- `BQ_CALL_ATTEMPTS_TABLE`
- `BQ_BULK_UPLOADS_TABLE`
- `PUBSUB_TOPIC`
- `BULK_UPLOAD_BUCKET`
- `DATAFLOW_ENABLED`
- `DATAFLOW_PROJECT_ID`
- `DATAFLOW_REGION`
- `DATAFLOW_TEMP_LOCATION`
- `DATAFLOW_STAGING_LOCATION`
- `DATAFLOW_TEMPLATE_GCS_PATH`
- `DATAFLOW_SERVICE_ACCOUNT_EMAIL`

The Cloud Run call worker service uses:

- `BQ_CALL_ATTEMPTS_TABLE`

## Bulk Upload

Download the CSV template from:

```text
/habi/data_crawling/bulk_phone_template.csv
```

Open the JSON example from:

```text
/habi/data_crawling/bulk_phone_sample.json
```

Upload a file with:

```text
POST /habi/data_crawling/bulk_phone_upload
multipart field: bulk_file
```

Required columns/keys:

```text
nombre,descripcion,telefono,latitude,longitude,maps_url,photo_url
```

Examples live in:

```text
examples/bulk_phone_template.csv
examples/bulk_phone_sample.json
```
