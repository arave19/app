# Habi Form App

Flask application for:

- Evidence form UI.
- Google Maps URL coordinate extraction.
- Phone OCR detection with PaddleOCR before submit.
- Photo upload to Cloud Storage.
- Form persistence to BigQuery.
- Submission event publication to Pub/Sub.
- Fake call worker endpoint for Pub/Sub push.

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
gcloud builds submit . --config cloudbuild.yaml --project aravel-344022 --substitutions _REGION=us-central1,_AR_REPOSITORY=habi,_IMAGE_NAME=habi-form-app
```

## Runtime Environment

The Cloud Run app service uses:

- `IMAGE_BUCKET`
- `BQ_SUBMISSIONS_TABLE`
- `BQ_CALL_ATTEMPTS_TABLE`
- `PUBSUB_TOPIC`

The Cloud Run call worker service uses:

- `BQ_CALL_ATTEMPTS_TABLE`
