FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=3000

# Шрифт с иероглифами и хангылем для карточек японских, китайских и корейских номеров
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Без смены пользователя: постоянные тома хостингов часто принадлежат root,
# и от другого пользователя база в них не создастся
RUN mkdir -p /app/data

# Bothost и похожие хостинги передают порт в PORT (по умолчанию 3000)
EXPOSE 3000
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT', '3000'), timeout=4)" || exit 1

CMD ["python", "run.py"]
