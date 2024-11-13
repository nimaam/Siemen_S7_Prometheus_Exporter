ENV DEBIAN_FRONTEND=dialog

# Install Python dependencies
RUN pip3 install --no-cache-dir python-snap7 prometheus_client pyyaml

# Set working directory
WORKDIR /app

# Copy application code
COPY ./exporter.py /app/
# Expose Prometheus metrics port
EXPOSE 9712

# Run the exporter
CMD ["python", "exporter.py"]
