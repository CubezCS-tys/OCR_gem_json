import { NextResponse } from "next/server";
import { isValidDocId } from "@/lib/constants";
import { extractHtmlPage } from "@/lib/documents.server";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string; pageIndex: string }> }
) {
  const { docId, pageIndex: pageIndexStr } = await params;

  if (!isValidDocId(docId)) {
    return NextResponse.json({ error: "Invalid document ID" }, { status: 400 });
  }

  const pageIndex = parseInt(pageIndexStr, 10);
  if (isNaN(pageIndex) || pageIndex < 0) {
    return NextResponse.json({ error: "Invalid page index" }, { status: 400 });
  }

  const html = extractHtmlPage(docId, pageIndex);
  if (!html) {
    return NextResponse.json({ error: "Page not found" }, { status: 404 });
  }

  return new NextResponse(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
