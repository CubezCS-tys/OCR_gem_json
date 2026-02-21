FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy configuration files first
COPY tsconfig.json ./
COPY next.config.js ./
COPY postcss.config.js ./
COPY tailwind.config.ts ./

# Copy source directories
COPY app ./app
COPY components ./components
COPY lib ./lib

# Build the Next.js app
RUN npm run build

# Expose port
EXPOSE 5000

# Set port environment variable
ENV PORT=5000

# Start the app
CMD ["npm", "start"]
