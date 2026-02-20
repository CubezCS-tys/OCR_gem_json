"use client";

import { use } from "react";
import ViewerShell from "@/components/viewer/ViewerShell";

export default function ViewerPage({
  params,
}: {
  params: Promise<{ docId: string }>;
}) {
  const { docId } = use(params);

  return <ViewerShell docId={docId} />;
}
