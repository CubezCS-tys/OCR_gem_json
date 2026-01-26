import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

// Use environment variable with fallback
const OUTPUTS_DIR = path.resolve(
  process.cwd(),
  process.env.OUTPUTS_DIR || "../outputs"
);

export async function GET(
  request: NextRequest,
  { params }: { params: { fileName: string } }
) {
  try {
    const fileName = params.fileName;

    // Sanitize fileName to prevent path traversal attacks
    const sanitizedFileName = path.basename(fileName);
    if (sanitizedFileName !== fileName || fileName.includes("..")) {
      return NextResponse.json(
        { error: "Invalid fileName" },
        { status: 400 }
      );
    }

    const jsonPath = path.join(OUTPUTS_DIR, `${sanitizedFileName}.json`);

    // Check if file exists
    await fs.access(jsonPath);

    // Read and parse JSON
    const jsonContent = await fs.readFile(jsonPath, "utf-8");
    const documentData = JSON.parse(jsonContent);

    return NextResponse.json(documentData);
  } catch (error) {
    console.error("Error loading document:", error);
    return NextResponse.json(
      { error: "Failed to load document" },
      { status: 500 }
    );
  }
}
