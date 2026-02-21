import { NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

export async function GET() {
  try {
    const baseDir = path.join(process.cwd(), "..");
    
    // Folders to ignore
    const ignoredFolders = [
      "outputs",
      "output_batch",
      "output_batch_2",
      "output_batch_3",
      "output_gem_1",
      "output_test",
      "json_outputs",
      "image_resize",
      "html_only_testing",
      "json_only_testing",
    ];
    
    // Read all directories in the parent folder
    const entries = await fs.readdir(baseDir, { withFileTypes: true });
    
    // Filter for directories that likely contain outputs
    // (contain .json or .html files)
    const folders = await Promise.all(
      entries
        .filter((entry) => entry.isDirectory())
        .filter((entry) => !entry.name.startsWith('.') && entry.name !== 'node_modules')
        .filter((entry) => entry.name === 'output_run1' || !ignoredFolders.includes(entry.name))
        .map(async (entry) => {
          const folderPath = path.join(baseDir, entry.name);
          try {
            const files = await fs.readdir(folderPath);
            const hasOutputFiles = files.some(f => f.endsWith('.json') || f.endsWith('.html'));
            return hasOutputFiles ? entry.name : null;
          } catch {
            return null;
          }
        })
    );
    
    // Filter out nulls and sort
    const validFolders = folders
      .filter((f): f is string => f !== null)
      .sort();
    
    return NextResponse.json({ folders: validFolders });
  } catch (error) {
    console.error("Failed to load folders:", error);
    return NextResponse.json({ folders: [] });
  }
}
