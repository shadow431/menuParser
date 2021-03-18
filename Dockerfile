FROM python:alpine

COPY requirements.txt /

RUN apk add gcc g++ make libffi-dev openssl-dev && pip3 install -r /requirements.txt && apk del gcc g++ make libffi-dev openssl-dev

COPY ./src /app
WORKDIR /app

ENV server='api.smartsheet.com'
ENV countLimit=False
ENV debug=False
ENV smartsheetDown=True
ENV smartsheetUp=True

CMD ["python3", "menuParser.py"]
