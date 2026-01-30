import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { exec } from "child_process";
import { promisify } from "util";
import { OUTPUTS_DIR, REBUILD_SCRIPT } from "@/lib/config";

const execAsync = promisify(exec);

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

    console.log(`JSON saved successfully: ${jsonPath}`);

    // Try to regenerate HTML (but don't fail if it doesn't work)
    const htmlPath = path.join(OUTPUTS_DIR, `${fileName}.html`);
    let htmlRegenerated = false;
    let htmlError = null;

    try {
      // Check if the script exists
      await fs.access(REBUILD_SCRIPT);

      const { stdout, stderr } = await execAsync(
        `python3 "${REBUILD_SCRIPT}" "${jsonPath}" "${htmlPath}"`,
        { timeout: 30000 } // 30 second timeout
      );

      if (stderr && !stderr.includes('WARNING')) {
        console.error("Python stderr:", stderr);
      }

      console.log("HTML regeneration output:", stdout);
      htmlRegenerated = true;
    } catch (error: any) {
      console.error("Error running Python script (non-fatal):", error.message || error);
      htmlError = error.message || "Failed to regenerate HTML";
      // Don't fail the request - JSON was saved successfully
    }

    return NextResponse.json({
      success: true,
      message: htmlRegenerated
        ? "Document saved and HTML regenerated"
        : "Document saved (HTML regeneration skipped)",
      jsonPath: `${fileName}.json`,
      htmlPath: htmlRegenerated ? `${fileName}.html` : undefined,
      warning: htmlError ? `HTML regeneration failed: ${htmlError.split('\n')[0]}` : undefined,
    });
  } catch (error: any) {
    console.error("Error saving document:", error);
    return NextResponse.json(
      { error: error.message || "Failed to save document" },
      { status: 500 }
    );
  }
}
