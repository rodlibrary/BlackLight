# One image for the three Lambda functions (webhook, convert, reconcile) and the CLI.
# Build from the repository root, since it includes the ingest package's metadata mappers:
#   docker build -f iiif/Dockerfile -t preservica-iiif .
# Debian's libvips includes JPEG 2000 (openjpeg), which Preservica access copies often use.
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends libvips42 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /var/task
COPY iiif/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt awslambdaric

COPY ingest/ ingest/
COPY iiif/preservica_iiif/ preservica_iiif/

# libvips spills large images to disk here; Lambda's only writable folder is /tmp.
ENV TMPDIR=/tmp PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["preservica_iiif.handlers.convert"]
