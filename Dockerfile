# One image definition for both services:
#   docker build --build-arg SERVICE=cloud   -t hospital-cloud .
#   docker build --build-arg SERVICE=gateway -t hospital-gateway .
# Keys are NOT baked in: mount them read-only at /app/keys.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY cloud ./cloud
COPY gateway ./gateway
RUN useradd --create-home app && chown -R app /app
USER app
ARG SERVICE=cloud
ENV SERVICE=${SERVICE} \
    CLOUD_HOST=0.0.0.0 \
    GATEWAY_HOST=0.0.0.0 \
    CLOUD_DEBUG_ENDPOINTS=0 \
    PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python -m ${SERVICE}.${SERVICE}_service"]
