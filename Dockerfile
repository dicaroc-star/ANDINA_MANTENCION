FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 andina
COPY server.py service.py schema.py security.py web.py ./
COPY index.html app.js styles.css ./
USER andina
EXPOSE 10000
CMD ["python", "web.py"]
