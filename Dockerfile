FROM python:3.12-slim

WORKDIR /app

# curl fetches the subtitle track from archive.org.
# ffmpeg is load-bearing, not a convenience: the page cuts the real frame of the
# real film at each illegal cue's own in-time, straight from the archive.org
# source. Without it the page still renders and says honestly that it could not
# cut a frame, but the visual argument, a line of dialogue on the frame it is
# too fast to read on, disappears.
RUN apt-get update && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST=1788986095
RUN echo "cachebust=${CACHEBUST}"

ARG CUEPASS_BUST=20260910020455
RUN echo cuepass_bust=$CUEPASS_BUST
COPY *.py ./

# The pre-measured run the page opens on, and the fixture track. Without these
# the first visitor gets an empty page, which is the whole problem they solve.
COPY data ./data

# Cloud Run's filesystem is read-only outside /tmp, so a run finished by this
# container is written here rather than back into the image.
ENV CUEPASS_RUN_DIR=/tmp/cuepass-runs

ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]



# bust 20260910020455
