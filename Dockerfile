FROM python:3.11-slim

WORKDIR /app

# TTF fonts for PDF report generation (report_generator falls back to these)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN sed -i 's/eip712_name="USDC"/eip712_name="USD Coin"/g' /usr/local/lib/python3.11/site-packages/fastapi_x402/networks.py

COPY main.py .
COPY agent_controller.py .
COPY wallet_interface.py .
COPY audit_logger.py .
COPY population_controller.py .
COPY payment_logger.py .
COPY stripe_webhook.py .
COPY notify.py .
COPY scripts/report_generator.py scripts/report_generator.py
COPY scripts/revenue_ledger.py scripts/revenue_ledger.py
COPY static/ static/
COPY templates/ templates/

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
