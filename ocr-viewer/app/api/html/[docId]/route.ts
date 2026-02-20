import { NextResponse } from "next/server";
import fs from "fs";
import { isValidDocId, getHtmlPath } from "@/lib/constants";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string }> }
) {
  const { docId } = await params;

  if (!isValidDocId(docId)) {
    return NextResponse.json({ error: "Invalid document ID" }, { status: 400 });
  }

  const htmlPath = getHtmlPath(docId);
  if (!fs.existsSync(htmlPath)) {
    return NextResponse.json({ error: "HTML not found" }, { status: 404 });
  }

  const html = fs.readFileSync(htmlPath, "utf-8");

  return new NextResponse(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
