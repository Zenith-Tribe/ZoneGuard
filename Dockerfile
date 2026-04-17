FROM python:3.12-slim

WORKDIR /app

# Configure pip
RUN pip config set global.timeout 120 && \
    pip config set global.index-url https://pypi.org/simple/

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

ENV PORT=8000
EXPOSE ${PORT}

# Run seed script to create tables, then start server
CMD sh -c "python db/seed.py && uvicorn main:app --host 0.0.0.0 --port ${PORT}"
