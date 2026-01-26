import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

// Use environment variable with fallback
const PDFS_DIR = path.resolve(
  process.cwd(),
  process.env.PDFS_DIR || "../pdfs"
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

    const pdfPath = path.join(PDFS_DIR, `${sanitizedFileName}.pdf`);

    // Check if file exists
    await fs.access(pdfPath);

    // Read PDF file
    const pdfBuffer = await fs.readFile(pdfPath);

    // Return PDF with appropriate headers
    return new NextResponse(pdfBuffer, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${sanitizedFileName}.pdf"`,
      },
    });
  } catch (error) {
    console.error("Error loading PDF:", error);
    return NextResponse.json(
      { error: "Failed to load PDF" },
      { status: 500 }
    );
  }
}
