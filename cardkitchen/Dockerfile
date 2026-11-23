ARG BUILD_FROM
FROM ${BUILD_FROM}

# Texterkennung (Tesseract, deutsch + englisch) und PDF-Werkzeuge für den kostenlosen Leser
RUN apk add --no-cache \
        tesseract-ocr \
        tesseract-ocr-data-deu \
        tesseract-ocr-data-eng \
        poppler-utils

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY app /opt/cardkitchen/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh
WORKDIR /opt/cardkitchen

ENV CK_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

CMD ["/run.sh"]
