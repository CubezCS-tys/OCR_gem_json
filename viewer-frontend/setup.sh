#!/bin/bash

# Setup script for OCR Viewer Frontend

echo "🚀 Setting up OCR Viewer Frontend..."
echo ""

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo "✅ npm version: $(npm --version)"
echo ""

# Check if we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Error: package.json not found. Please run this script from the viewer-frontend directory."
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
npm install

if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo ""
echo "✅ Dependencies installed successfully!"
echo ""

# Check if parent directories exist
if [ ! -d "../outputs" ]; then
    echo "⚠️  Warning: ../outputs directory not found"
    echo "   The viewer needs this directory to load documents"
fi

if [ ! -d "../pdfs" ]; then
    echo "⚠️  Warning: ../pdfs directory not found"
    echo "   The viewer needs this directory to load PDF files"
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "To start the development server:"
echo "  npm run dev"
echo ""
echo "To build for production:"
echo "  npm run build"
echo "  npm start"
echo ""
echo "The viewer will be available at: http://localhost:3000"
echo ""
