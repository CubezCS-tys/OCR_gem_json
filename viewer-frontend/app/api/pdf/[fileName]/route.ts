import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

const PDFS_DIR = path.join(process.cwd(), "../pdfs");

export async function GET(
  request: NextRequest,
  { params }: { params: { fileName: string } }
) {
  try {
    const fileName = params.fileName;
    const pdfPath = path.join(PDFS_DIR, `${fileName}.pdf`);

    // Check if file exists
    await fs.access(pdfPath);

    // Read PDF file
    const pdfBuffer = await fs.readFile(pdfPath);

    // Return PDF with appropriate headers
    return new NextResponse(pdfBuffer, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${fileName}.pdf"`,
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
