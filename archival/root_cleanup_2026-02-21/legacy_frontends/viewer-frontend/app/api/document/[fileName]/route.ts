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
    const jsonPath = path.join(OUTPUTS_DIR, `${fileName}.json`);

    // Check if file exists
    await fs.access(jsonPath);

    // Read and parse JSON
    const jsonContent = await fs.readFile(jsonPath, "utf-8");
    const documentData = JSON.parse(jsonContent);

    // Normalize data: ensure pages have page_number field
    if (documentData.pages && Array.isArray(documentData.pages)) {
      documentData.pages = documentData.pages.map((page: any, index: number) => ({
        ...page,
        // If page_number doesn't exist, create it from index (0-based to 1-based)
        page_number: page.page_number !== undefined ? page.page_number : index + 1,
        // Ensure required fields have defaults
        text_blocks: page.text_blocks || page.blocks || [],
        tables: page.tables || [],
        images: page.images || [],
        text_direction: page.text_direction || page.page_direction || 'ltr',
        has_multi_column: page.has_multi_column !== undefined ? page.has_multi_column : false,
      }));
    }
    
    // Ensure metadata exists
    if (!documentData.metadata) {
      documentData.metadata = {
        total_pages: documentData.pages?.length || 0,
      };
    }

    return NextResponse.json(documentData);
  } catch (error) {
    console.error("Error loading document:", error);
    return NextResponse.json(
      { error: "Failed to load document" },
      { status: 500 }
    );
  }
}
