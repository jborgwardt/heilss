FROM python:3.13-alpine
RUN pip install --no-cache-dir pyyaml==6.0.3 && adduser -D -u 1000 app && mkdir /data && chown 1000:1000 /data
WORKDIR /app
COPY --chown=1000:1000 . /app
LABEL org.opencontainers.image.source="https://github.com/jborgwardt/heilss"
USER 1000:1000
ENV PORT=8080 HEILSS_DATA=/data PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
