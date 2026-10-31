FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LD_LIBRARY_PATH=/opt/voice/lib

ARG WHISPER_CPP_VERSION=v1.7.4

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates ffmpeg git cmake build-essential \
    && rm -rf /var/lib/apt/lists/*

# Whisper.cpp compilé depuis les sources (recette éprouvée think-tank : v1.7.4, SDL2 off).
RUN set -eux; \
    mkdir -p /opt/voice/bin /opt/voice/lib; \
    git clone --depth 1 --branch "${WHISPER_CPP_VERSION}" https://github.com/ggml-org/whisper.cpp.git /tmp/whisper.cpp; \
    cmake -S /tmp/whisper.cpp -B /tmp/whisper.cpp/build -DWHISPER_SDL2=OFF; \
    cmake --build /tmp/whisper.cpp/build --config Release -j"$(nproc)"; \
    find /tmp/whisper.cpp/build -type f -name whisper-cli -exec cp {} /opt/voice/bin/whisper-cli \; ; \
    find /tmp/whisper.cpp/build \( -type f -o -type l \) \( -name 'libwhisper.so*' -o -name 'libggml*.so*' \) -exec cp -a {} /opt/voice/lib/ \; ; \
    chmod +x /opt/voice/bin/whisper-cli; \
    rm -rf /tmp/whisper.cpp

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
