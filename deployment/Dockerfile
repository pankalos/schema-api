FROM python:3.11-slim-bookworm as build

RUN mkdir -p /schema-api

WORKDIR /schema-api-build

RUN python -m venv /venv

ENV PATH="/venv/bin:$PATH"

RUN pip install --upgrade pip

RUN pip install psycopg2-binary uvicorn pipenv

COPY Pipfile Pipfile.lock ./

RUN pipenv requirements > requirements.txt && pip install -r requirements.txt --no-cache-dir

FROM python:3.11-alpine

ENV SCHEMA_API_DEPLOYMENT production

EXPOSE 8000

COPY --from=build /venv /venv

ENV PATH="/venv/bin:$PATH"

RUN pip3 uninstall -y pyopenssl cryptography pyasn1 cffi psycopg2-binary && pip3 install --no-cache-dir pyopenssl cryptography pyasn1 cffi psycopg2-binary

WORKDIR /schema-api

COPY schema-api/ .

# ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "schema_api.asgi:application", "--host", "0.0.0.0", "--port", "8000"]

