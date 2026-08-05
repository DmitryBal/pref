FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --upgrade pip

RUN pip install \
    fastapi \
    uvicorn \
    websockets \
    pydantic

RUN pip install -e .

EXPOSE 8000

CMD [
    "uvicorn",
    "web.backend.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000"
]