FROM python:3.12-slim

WORKDIR /app

# Configure pip to use Google DNS-resolvable PyPI mirror and longer timeout
RUN pip config set global.timeout 120 && \
    pip config set global.index-url https://pypi.org/simple/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE ${PORT}

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
