FROM python:alpine

COPY requirements.txt /

RUN apk add gcc g++ make libffi-dev openssl-dev && pip3 install -r /requirements.txt && apk del gcc g++ make libffi-dev openssl-dev

COPY . /app
#WORKDIR /app # <--??

RUN chmod a+x /app/run.sh
CMD /app/run.sh
