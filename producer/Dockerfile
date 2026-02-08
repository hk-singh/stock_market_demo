# Multi-stage build for smaller image size
FROM python:3.9-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for layer caching)
COPY producer/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY producer/producer.py .
COPY producer/websocket_handler.py .

# Copy shared module
COPY shared/ ./shared/

# Update PATH to use user-installed packages
ENV PATH=/root/.local/bin:$PATH

# Set Python to run in unbuffered mode (logs appear immediately)
ENV PYTHONUNBUFFERED=1

# Expose health check port
EXPOSE 8000

# Run the producer
CMD ["python", "producer.py"]
