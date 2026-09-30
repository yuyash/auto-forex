# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM public.ecr.aws/docker/library/python:3.11-slim AS build

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --target /install .

FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/python

WORKDIR /app
COPY --from=build /install /opt/python

USER 10001
CMD ["python", "-m", "autoforex.handlers.stream"]
