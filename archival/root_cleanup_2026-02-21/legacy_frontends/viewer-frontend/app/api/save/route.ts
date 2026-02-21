import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);
const OUTPUTS_DIR = path.join(process.cwd(), "../outputs");

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { fileName, documentData } = body;

    if (!fileName || !documentData) {
      return NextResponse.json(
        { error: "Missing fileName or documentData" },
        { status: 400 }
      );
    }

    // Save updated JSON
    const jsonPath = path.join(OUTPUTS_DIR, `${fileName}.json`);
    await fs.writeFile(jsonPath, JSON.stringify(documentData, null, 2), "utf-8");

    // Call Python script to regenerate HTML
    // The rebuild_html_simple.py script accepts JSON path and output HTML path
    const htmlPath = path.join(OUTPUTS_DIR, `${fileName}.html`);
    const pythonScript = path.join(process.cwd(), "../rebuild_html_simple.py");

    try {
      const { stdout, stderr } = await execAsync(
        `python3 "${pythonScript}" "${jsonPath}" "${htmlPath}"`
      );
      
      if (stderr) {
        console.error("Python stderr:", stderr);
      }
      
      console.log("HTML regeneration output:", stdout);
    } catch (error) {
      console.error("Error running Python script:", error);
      return NextResponse.json(
        { error: "Failed to regenerate HTML" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      message: "Document saved and HTML regenerated",
      htmlPath: `${fileName}.html`,
    });
  } catch (error) {
    console.error("Error saving document:", error);
    return NextResponse.json(
      { error: "Failed to save document" },
      { status: 500 }
    );
  }
}
