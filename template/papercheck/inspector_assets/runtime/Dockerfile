FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && python3 -m venv /opt/pdf-python \
    && /opt/pdf-python/bin/pip install --no-cache-dir PyMuPDF==1.26.7 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/papercheck
COPY app ./app
ENV HOST=0.0.0.0 PORT=4178 PAPERCHECK_DATA=/srv/papercheck/data PAPERCHECK_REVIEWS=/srv/papercheck/reviews PAPERCHECK_PYTHON=/opt/pdf-python/bin/python
USER node
EXPOSE 4178
CMD ["node", "app/server.mjs"]
