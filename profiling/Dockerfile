FROM python:3.10-slim

# Install 'procps' to use the 'ps' command inside the container for profiling
RUN apt-get update && apt-get install -y procps && rm -rf /var/lib/apt/lists/*

# Set the working directory to mirror the project package structure
WORKDIR /app/backend/runtime

# Install Python requirements
COPY backend/runtime/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY backend/runtime/ .

# Copy the entrypoint script
COPY profiling/entrypoint.sh .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

EXPOSE 8000

# Run the wrapper script
CMD ["./entrypoint.sh"]
