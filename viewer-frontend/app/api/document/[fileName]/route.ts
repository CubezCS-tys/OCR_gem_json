import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

const OUTPUTS_DIR = path.join(process.cwd(), "../output_batch");

export async function GET(
  request: NextRequest,
  { params }: { params: { fileName: string } }
) {
  try {
    const fileName = params.fileName;
    const jsonPath = path.join(OUTPUTS_DIR, `${fileName}.json`);

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
