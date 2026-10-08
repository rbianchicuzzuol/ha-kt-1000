FROM python:3.13-slim-bookworm
LABEL io.hass.type="app" io.hass.version="0.11.0" io.hass.arch="amd64|aarch64"
WORKDIR /opt/kt1000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "app.server"]
