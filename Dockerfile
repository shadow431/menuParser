FROM python:alpine

COPY requirements.txt /

RUN apk add --no-cache --update gcc g++ make libffi-dev openssl-dev rust && \
    pip3 install -r /requirements.txt && \
    apk del gcc g++ make libffi-dev openssl-dev

COPY ./src /app
WORKDIR /app

ENV server='api.smartsheet.com'
ENV countLimit=False
ENV debug=False
ENV smartsheet_debug=False
ENV pdf_debug=False
ENV parser_debug=False
ENV smartsheetDown=True
ENV smartsheetUp=True
ENV sslVerify=True

CMD ["python3", "menuParser.py"]
