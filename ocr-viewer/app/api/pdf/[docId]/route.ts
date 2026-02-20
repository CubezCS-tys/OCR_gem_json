import { NextResponse } from "next/server";
import fs from "fs";
import { isValidDocId, getPdfPath } from "@/lib/constants";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string }> }
) {
  const { docId } = await params;

  if (!isValidDocId(docId)) {
    return NextResponse.json({ error: "Invalid document ID" }, { status: 400 });
  }

  const pdfPath = getPdfPath(docId);
  if (!fs.existsSync(pdfPath)) {
    return NextResponse.json({ error: "PDF not found" }, { status: 404 });
  }

  const fileBuffer = fs.readFileSync(pdfPath);

  return new NextResponse(fileBuffer, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${docId}.pdf"`,
      "Cache-Control": "public, max-age=3600, immutable",
    },
  });
}
