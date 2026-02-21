import { NextResponse } from "next/server";
import { listDocuments } from "@/lib/documents.server";

export async function GET() {
  const documents = listDocuments();
  return NextResponse.json(documents);
}
