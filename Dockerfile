FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sentinel sentinel
COPY README.md .
EXPOSE 8000
CMD ["uvicorn", "sentinel.api:app", "--host", "0.0.0.0", "--port", "8000"]
