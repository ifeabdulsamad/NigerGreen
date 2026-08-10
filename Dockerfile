# NaijaGreen Chat — Docker image (TRD §11.2)
FROM python:3.11-slim

WORKDIR /app

# System deps: none required at runtime; pip is enough.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Upload sandbox
RUN mkdir -p data/uploads

EXPOSE 8501

# TRD specifies curl for the healthcheck, but python:slim ships no curl;
# urllib hits the same Streamlit health endpoint (documented deviation).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
