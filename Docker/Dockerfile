FROM python:3.11-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*
# Unprivileged runtime user. The mount points are pre-created and owned by it so that
# *fresh* named volumes inherit the ownership; volumes created by an older root-running
# image are fixed once by deploy.sh (--up).
ARG APP_UID=10001
RUN useradd --uid ${APP_UID} --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/fonts /app/ArtistLogos /app/Logs /app/rembg_models \
    && chown app:app /app/fonts /app/ArtistLogos /app/Logs /app/rembg_models
# Dependencies first so code edits don't invalidate the (large) pip layers.
COPY requirements.txt requirements-rembg.txt ./
# rembg + onnxruntime + scipy are ~1GB; skip them when background removal is off.
ARG INSTALL_REMBG=true
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_REMBG" = "true" ]; then pip install --no-cache-dir -r requirements-rembg.txt; fi
# Code stays root-owned and not writable by the app user, whatever mode the build
# context had (the shared project mount often has 666 files).
COPY . .
RUN chmod -R go-w,a+rX /app
USER app
EXPOSE 5000
# glibc's malloc opens a new memory arena per thread and rarely returns freed
# arenas to the OS — on a long-running process doing lots of variable-sized
# PIL/numpy/onnxruntime allocations (every image transform, every rembg call)
# this shows up as RSS that climbs and plateaus high even without a real leak.
# Capping arenas keeps glibc reusing a small, bounded pool instead of growing one.
ENV MALLOC_ARENA_MAX=2
# Unbuffered stdout so print() output reaches `docker logs` immediately.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["python", "app.py"]
