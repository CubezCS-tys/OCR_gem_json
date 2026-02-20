import { NextResponse } from "next/server";
import fs from "fs";
import { isValidDocId, getSearchablePdfPath } from "@/lib/constants";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string }> }
) {
  const { docId } = await params;

  if (!isValidDocId(docId)) {
    return NextResponse.json({ error: "Invalid document ID" }, { status: 400 });
  }

  const pdfPath = getSearchablePdfPath(docId);
  if (!fs.existsSync(pdfPath)) {
    return NextResponse.json({ error: "Searchable PDF not found" }, { status: 404 });
  }

  const fileBuffer = fs.readFileSync(pdfPath);

  return new NextResponse(fileBuffer, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${docId}_searchable.pdf"`,
      "Cache-Control": "public, max-age=3600, immutable",
    },
  });
}
