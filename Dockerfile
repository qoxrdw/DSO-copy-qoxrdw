
FROM python:3.10-slim-bookworm AS builder


RUN apt-get update && \
    apt-get install --no-install-recommends -y \
    gcc=4:12.2.0-3 \
    libpq-dev=15.14-0+deb12u1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY requirements.txt .

RUN pip install --no-cache-dir --compile -r requirements.txt

FROM python:3.10-alpine3.20

RUN apk add --no-cache \
    libc6-compat=1.1.0-r4 \
    gcompat=1.1.0-r4\
    libgcc=13.2.1_git20240309-r1 \
    libstdc++=13.2.1_git20240309-r1 \
    libpq=16.11-r0 \
    curl=8.14.1-r2

RUN addgroup -S app && adduser -S app -u 1000 -G app

WORKDIR /usr/src/app
RUN chown app:app /usr/src/app

COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

COPY --chown=app:app . .

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
