import { NextResponse } from "next/server";
import { isValidDocId } from "@/lib/constants";
import { getDocumentMetadata } from "@/lib/documents.server";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string }> }
) {
  const { docId } = await params;

  if (!isValidDocId(docId)) {
    return NextResponse.json({ error: "Invalid document ID" }, { status: 400 });
  }

  const metadata = getDocumentMetadata(docId);
  if (!metadata) {
    return NextResponse.json({ error: "Document not found" }, { status: 404 });
  }

  return NextResponse.json(metadata);
}
