FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 && rm -rf /var/lib/apt-lists/*
RUN pip install --no-cache-dir plexapi requests Pillow Flask cloudscraper flask-limiter "fonttools[woff]" cairosvg rembg onnxruntime
COPY . .
EXPOSE 5000
# glibc's malloc opens a new memory arena per thread and rarely returns freed
# arenas to the OS — on a long-running process doing lots of variable-sized
# PIL/numpy/onnxruntime allocations (every image transform, every rembg call)
# this shows up as RSS that climbs and plateaus high even without a real leak.
# Capping arenas keeps glibc reusing a small, bounded pool instead of growing one.
ENV MALLOC_ARENA_MAX=2
CMD ["python", "app.py"]