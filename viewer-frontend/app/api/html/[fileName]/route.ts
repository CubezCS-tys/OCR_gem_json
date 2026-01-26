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

    const htmlPath = path.join(OUTPUTS_DIR, `${sanitizedFileName}.html`);

    // Check if file exists
    await fs.access(htmlPath);

    // Read HTML file
    const htmlContent = await fs.readFile(htmlPath, "utf-8");

    // Return HTML with appropriate headers
    return new NextResponse(htmlContent, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
      },
    });
  } catch (error) {
    console.error("Error loading HTML:", error);
    return NextResponse.json(
      { error: "Failed to load HTML" },
      { status: 500 }
    );
  }
}
