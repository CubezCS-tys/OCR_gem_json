import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

// Use environment variables with fallbacks
const OUTPUTS_DIR = path.resolve(
  process.cwd(),
  process.env.OUTPUTS_DIR || "../outputs"
);
const PYTHON_PATH = process.env.PYTHON_PATH || "python3";

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

    // Sanitize fileName to prevent path traversal attacks
    const sanitizedFileName = path.basename(fileName);
    if (sanitizedFileName !== fileName || fileName.includes("..")) {
      return NextResponse.json(
        { error: "Invalid fileName" },
        { status: 400 }
      );
    }

    // Save updated JSON
    const jsonPath = path.join(OUTPUTS_DIR, `${sanitizedFileName}.json`);
    await fs.writeFile(jsonPath, JSON.stringify(documentData, null, 2), "utf-8");

    // Call Python script to regenerate HTML
    // The rebuild_html_simple.py script accepts JSON path and output HTML path
    const htmlPath = path.join(OUTPUTS_DIR, `${sanitizedFileName}.html`);
    const pythonScript = path.join(process.cwd(), "../rebuild_html_simple.py");

    // Verify Python script exists
    try {
      await fs.access(pythonScript);
    } catch {
      console.error("Python script not found:", pythonScript);
      return NextResponse.json(
        { error: "HTML regeneration script not found" },
        { status: 500 }
      );
    }

    try {
      const { stdout, stderr } = await execAsync(
        `${PYTHON_PATH} "${pythonScript}" "${jsonPath}" "${htmlPath}"`
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
      htmlPath: `${sanitizedFileName}.html`,
    });
  } catch (error) {
    console.error("Error saving document:", error);
    return NextResponse.json(
      { error: "Failed to save document" },
      { status: 500 }
    );
  }
}
