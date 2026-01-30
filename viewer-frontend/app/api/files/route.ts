import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

// Use environment variables with fallbacks
const OUTPUTS_DIR = process.env.OUTPUTS_DIR || path.join(process.cwd(), "../output_batch");
const PDFS_DIR = process.env.PDFS_DIR || path.join(process.cwd(), "../pdfs");

// Cache duration in seconds (5 minutes by default)
const CACHE_DURATION = 300;

interface FileInfo {
  name: string;
  pdfPath?: string;
  jsonPath: string;
  htmlPath?: string;
  jsonSize?: number;
  modifiedAt?: string;
}

export async function GET(request: NextRequest) {
  try {
    // Check if directories exist
    const [outputsExist, pdfsExist] = await Promise.all([
      fs.access(OUTPUTS_DIR).then(() => true).catch(() => false),
      fs.access(PDFS_DIR).then(() => true).catch(() => false),
    ]);

    if (!outputsExist) {
      return NextResponse.json(
        {
          error: "Outputs directory not found",
          details: `Expected directory at: ${OUTPUTS_DIR}`,
          suggestion: "Check OUTPUTS_DIR environment variable or create the directory"
        },
        { status: 404 }
      );
    }

    // Read files from outputs directory
    const files = await fs.readdir(OUTPUTS_DIR);

    // Find JSON files and their corresponding PDF/HTML files
    const jsonFiles = files.filter((f) => f.endsWith(".json"));

    if (jsonFiles.length === 0) {
      return NextResponse.json(
        {
          files: [],
          message: "No JSON files found in outputs directory"
        },
        {
          headers: {
            'Cache-Control': `public, max-age=${CACHE_DURATION}`,
          }
        }
      );
    }

    const fileInfos: FileInfo[] = await Promise.all(
      jsonFiles.map(async (jsonFile) => {
        const baseName = jsonFile.replace(".json", "");
        const htmlFile = `${baseName}.html`;
        const jsonPath = path.join(OUTPUTS_DIR, jsonFile);

        // Get file stats for size and modification time
        let jsonStats;
        try {
          jsonStats = await fs.stat(jsonPath);
        } catch {
          jsonStats = null;
        }

        // Check if corresponding files exist
        const htmlExists = files.includes(htmlFile);

        // Check if PDF exists in pdfs directory
        const pdfFile = `${baseName}.pdf`;
        const pdfPath = path.join(PDFS_DIR, pdfFile);
        const pdfExists = pdfsExist && await fs
          .access(pdfPath)
          .then(() => true)
          .catch(() => false);

        return {
          name: baseName,
          pdfPath: pdfExists ? pdfFile : undefined,
          jsonPath: jsonFile,
          htmlPath: htmlExists ? htmlFile : undefined,
          jsonSize: jsonStats?.size,
          modifiedAt: jsonStats?.mtime.toISOString(),
        };
      })
    );

    // Sort files by modification date (newest first)
    const sortedFiles = fileInfos.sort((a, b) => {
      if (!a.modifiedAt || !b.modifiedAt) return 0;
      return new Date(b.modifiedAt).getTime() - new Date(a.modifiedAt).getTime();
    });

    const response = NextResponse.json({
      files: sortedFiles,
      count: sortedFiles.length,
      outputsDir: OUTPUTS_DIR,
      pdfsDir: PDFS_DIR,
    });

    // Add caching headers
    response.headers.set('Cache-Control', `public, max-age=${CACHE_DURATION}, stale-while-revalidate=60`);

    return response;
  } catch (error) {
    console.error("Error loading files:", error);

    let errorMessage = "Failed to load files";
    let errorDetails = "";

    if (error instanceof Error) {
      errorMessage = error.message;
      errorDetails = error.stack || "";
    }

    return NextResponse.json(
      {
        error: errorMessage,
        details: process.env.NODE_ENV === 'development' ? errorDetails : undefined
      },
      { status: 500 }
    );
  }
}
