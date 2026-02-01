import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ fileName: string }> }
) {
  try {
    const { fileName } = await params;
    const { searchParams } = new URL(request.url);
    const folder = searchParams.get("folder") || "outputs";
    
    const OUTPUTS_DIR = path.join(process.cwd(), `../${folder}`);
    const htmlPath = path.join(OUTPUTS_DIR, `${fileName}.html`);

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
