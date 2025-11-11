FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN adduser --disabled-password --gecos "" appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY admin.py .
RUN chmod +x /app/admin.py && ln -s /app/admin.py /usr/local/bin/admin
RUN mkdir -p /data && chown -R appuser:appuser /data
ENV DB_PATH=/data/events.db
USER appuser
EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
