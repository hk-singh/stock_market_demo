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
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY simple_consumer.py .
COPY aggregator_consumer.py .
COPY storage_consumer.py .

# Create data directory for storage consumer
RUN mkdir -p /app/data

# Update PATH
ENV PATH=/root/.local/bin:$PATH

# Set Python to run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Default command (can be overridden)
CMD ["python", "simple_consumer.py"]

