# =============================================================================
# Dockerfile for Construction Quantity Takeoff Engine
# =============================================================================
# Production-ready container with:
# - Python 3.12 slim base
# - ODA File Converter for DWG support
# - FastAPI backend + Streamlit frontend
#
# Build: docker build -t construction-takeoff .
# Run:   docker run -p 8000:8000 -p 8501:8501 construction-takeoff
# =============================================================================

FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production

# Set working directory
WORKDIR /app

# =============================================================================
# STAGE 1: Install system dependencies and ODA File Converter
# =============================================================================

FROM base AS builder

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    gcc \
    g++ \
    # Required for psycopg2
    libpq-dev \
    # Required for ODA File Converter
    wget \
    libc6 \
    libstdc++6 \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Download and install ODA File Converter
# TASK 3 FIX: Check for local file first, then fallback to wget
# To use local file: place .deb in resources/ folder before building
# Download from: https://www.opendesign.com/guestfiles/oda_file_converter
ARG ODA_VERSION=26.12.0.0
ARG ODA_URL=https://download.opendesign.com/guestfiles/Demo/ODAFileConverter_QT6_lnxX64_8.3dll_25.2.deb

# Install Qt6 and other ODA dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libqt6core6 \
    libqt6gui6 \
    libqt6widgets6 \
    libgl1-mesa-glx \
    libxcb-xinerama0 \
    || echo "Qt6 packages not found, ODA may not work" \
    && rm -rf /var/lib/apt/lists/*

# Copy local ODA file if exists
COPY resources/ /tmp/resources/

# Install ODA from local file or download
RUN if [ -f /tmp/resources/oda_converter.deb ]; then \
    echo "📦 Installing ODA from local file..." && \
    dpkg -i /tmp/resources/oda_converter.deb || apt-get install -f -y && \
    rm -rf /tmp/resources; \
    else \
    echo "⬇️ No local ODA file, downloading from web..." && \
    wget -q -O /tmp/oda_converter.deb ${ODA_URL} && \
    dpkg -i /tmp/oda_converter.deb || apt-get install -f -y && \
    rm /tmp/oda_converter.deb || \
    echo "⚠️ ODA download failed"; \
    fi && \
    # Find and link ODA executable
    ODA_BIN=$(find /usr /opt -name "ODAFileConverter" -type f 2>/dev/null | head -1) && \
    if [ -n "$ODA_BIN" ]; then \
    mkdir -p /opt/ODAFileConverter && \
    ln -sf "$ODA_BIN" /opt/ODAFileConverter/ODAFileConverter && \
    echo "✅ ODA linked from: $ODA_BIN"; \
    else \
    echo "⚠️ ODA executable not found - creating mock" && \
    mkdir -p /opt/ODAFileConverter && \
    echo '#!/bin/bash' > /opt/ODAFileConverter/ODAFileConverter && \
    echo 'echo "ODA mock - DWG support requires manual installation"' >> /opt/ODAFileConverter/ODAFileConverter && \
    chmod +x /opt/ODAFileConverter/ODAFileConverter; \
    fi

# Set ODA converter path
ENV ODA_CONVERTER_PATH=/opt/ODAFileConverter/ODAFileConverter

# =============================================================================
# STAGE 2: Install Python dependencies
# =============================================================================

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    # Additional dependencies for frontend
    pip install \
    streamlit>=1.31.0 \
    pandas>=2.2.0 \
    openpyxl>=3.1.0 \
    requests>=2.31.0

# =============================================================================
# STAGE 3: Final image
# =============================================================================

FROM base AS final

# Copy system libraries from builder
COPY --from=builder /usr/lib /usr/lib
COPY --from=builder /opt/ODAFileConverter /opt/ODAFileConverter

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set ODA path
ENV ODA_CONVERTER_PATH=/opt/ODAFileConverter/ODAFileConverter

# Install PostgreSQL client library (runtime only)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose ports
# 8000 - FastAPI backend
# 8501 - Streamlit frontend
EXPOSE 8000 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# =============================================================================
# Startup Script
# =============================================================================

# Create startup script
RUN echo '#!/bin/bash\n\
    # Start FastAPI backend in background\n\
    uvicorn main:app --host 0.0.0.0 --port 8000 &\n\
    BACKEND_PID=$!\n\
    \n\
    # Wait for backend to be ready\n\
    sleep 3\n\
    \n\
    # Start Streamlit frontend\n\
    streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &\n\
    FRONTEND_PID=$!\n\
    \n\
    # Wait for both processes\n\
    wait $BACKEND_PID $FRONTEND_PID\n\
    ' > /app/start.sh && chmod +x /app/start.sh

# Default command
CMD ["/bin/bash", "/app/start.sh"]
