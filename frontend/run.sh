#!/bin/sh

# Server configuration from environment
PORT=${PORT:-3000}
API_BASE=${API_BASE:-http://localhost:8000}

# Validate connection to API
echo "Checking API at $API_BASE..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if curl -s -f "$API_BASE/health" > /dev/null 2>&1; then
    echo "API is ready!"
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  echo "Waiting for API... ($RETRY_COUNT/$MAX_RETRIES)"
  sleep 1
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "Warning: API not responding at $API_BASE"
fi

echo "Starting CI Engine Dashboard on port $PORT"
serve -s dist -l $PORT