FROM python:3.11-slim

WORKDIR /app
COPY carbon-frontier/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY carbon-frontier/ ./carbon-frontier/

WORKDIR /app/carbon-frontier
EXPOSE 8000
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000", "--no-reload"]
