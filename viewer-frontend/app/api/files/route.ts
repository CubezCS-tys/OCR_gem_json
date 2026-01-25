import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

const OUTPUTS_DIR = path.join(process.cwd(), "../outputs");
const PDFS_DIR = path.join(process.cwd(), "../pdfs");

export async function GET(request: NextRequest) {
  try {
    // Check if directories exist
    const outputsExist = await fs
      .access(OUTPUTS_DIR)
      .then(() => true)
      .catch(() => false);

    if (!outputsExist) {
      return NextResponse.json(
        { error: "Outputs directory not found" },
        { status: 404 }
      );
    }

    // Read files from outputs directory
    const files = await fs.readdir(OUTPUTS_DIR);
    
    // Find JSON files and their corresponding PDF/HTML files
    const jsonFiles = files.filter((f) => f.endsWith(".json"));
    
    const fileInfos = await Promise.all(
      jsonFiles.map(async (jsonFile) => {
        const baseName = jsonFile.replace(".json", "");
        const htmlFile = `${baseName}.html`;
        
        // Check if corresponding files exist
        const htmlExists = files.includes(htmlFile);
        
        // Check if PDF exists in pdfs directory
        const pdfFile = `${baseName}.pdf`;
        const pdfPath = path.join(PDFS_DIR, pdfFile);
        const pdfExists = await fs
          .access(pdfPath)
          .then(() => true)
          .catch(() => false);

        return {
          name: baseName,
          pdfPath: pdfExists ? pdfFile : undefined,
          jsonPath: jsonFile,
          htmlPath: htmlExists ? htmlFile : undefined,
        };
      })
    );

    // Filter out files without JSON
    const validFiles = fileInfos.filter((f) => f.jsonPath);

    return NextResponse.json({ files: validFiles });
  } catch (error) {
    console.error("Error loading files:", error);
    return NextResponse.json(
      { error: "Failed to load files" },
      { status: 500 }
    );
  }
}
