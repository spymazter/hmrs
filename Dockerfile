FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc libffi-dev libssl-dev tzdata nginx supervisor \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/cli ./cli
COPY backend/scripts ./scripts
COPY backend/tests ./tests
COPY --from=frontend-build /frontend/dist ./frontend/dist

COPY nginx-single.conf /etc/nginx/conf.d/default.conf
COPY supervisord.conf /etc/supervisor/conf.d/hrms.conf

RUN mkdir -p /app/data/pdfs /var/log/supervisor

EXPOSE 80

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/hrms.conf"]
