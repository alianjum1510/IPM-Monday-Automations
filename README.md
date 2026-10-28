# monday apps — one deployment, two apps

Two monday.com automation apps, deployed together on monday-code as **one app
on one port**. Each app lives untouched in its own folder:

```
main.py                    the one server: mounts each app under its own path (the only shared code)
main_test.py               checks each URL reaches its own app
Procfile                   web: uvicorn main:app  (what monday-code runs)
.mondaycoderc              Python 3.12
requirements.txt           pulls in both apps' requirements
pytest.ini                 runs all tests: main_test.py + both apps' own tests

company_enrichment/        Company Enrichment block (Flask)   - see company_enrichment/README.md
customer_name_split_py/    Split Customer Name block (FastAPI) - see customer_name_split_py/README.md
```

## URLs

monday-code gives the app one Version URL and one port (8080). The path after
the URL picks the app:

| Path | App | Set as the Execution URL of |
| --- | --- | --- |
| `POST /company-enrichment` | `company_enrichment/` | the **Company Enrichment** block |
| `POST /customer-name-split` (or `/customer-name-split/monday/split-name`) | `customer_name_split_py/` | the **Split Customer Name** block |
| `GET /`, `GET /health` | health check | — |

So a block's Execution URL is `<Version URL>/company-enrichment` or
`<Version URL>/customer-name-split`. Both blocks must be in the **same** monday
app, the one this code is deployed to.

## Settings

Set on that one app in the Developer Center (Environment variables / Secrets).
Both apps read from the same list:

| Key | Used by |
| --- | --- |
| `MONDAY_API_TOKEN` | both |
| `MONDAY_SIGNING_SECRET` | name split (the Signing Secret of **this** app) |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_MS`, … | enrichment (full list in company_enrichment/README.md) |
| `MONDAY_API_VERSION` | both - if set, both use it (defaults: enrichment `2024-10`, name split `2025-04`) |

On startup, `main.py` copies any setting the enrichment app needs from the
monday-code service into the process environment, because that app reads only
environment variables. After a deploy, check the log for `Config OK` (name
split) and the absence of `Missing environment variables` (enrichment).

## Run, test, deploy

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                               # all tests, both apps
.venv/bin/uvicorn main:app --port 8080         # both apps on :8080

npx @mondaycom/apps-cli code:push -i <APP_VERSION_ID> -d .
```

Everything runs from this root folder: the app folders hold only their code,
tests, `requirements.txt` and README.
