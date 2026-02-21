#!/bin/bash

# Build the Docker image
docker build -t ocr-frontend .

# Run the container
# - Port 3000 exposed
# - Access to parent directory for outputs/pdfs
docker run -d \
  --name ocr-frontend \
  -p 5000:5000 \
  -v "$(dirname "$PWD"):/data" \
  --restart unless-stopped \
  ocr-frontend

echo "Frontend started on http://localhost:5000"
echo "To view logs: docker logs -f ocr-frontend"
echo "To stop: docker stop ocr-frontend"
echo "To restart: docker restart ocr-frontend"
