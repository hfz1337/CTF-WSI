FROM python:3.8

RUN pip install beautifulsoup4 requests pymongo

COPY app /app
WORKDIR /app

RUN chmod +x entrypoint.sh

USER nobody

ENTRYPOINT ["./entrypoint.sh"]
