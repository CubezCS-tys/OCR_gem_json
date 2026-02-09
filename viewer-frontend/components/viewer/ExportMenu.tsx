"use client";

import { useState } from "react";
import { useViewerStore } from "@/lib/store";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Download, FileJson, FileText, FileCode } from "lucide-react";
import { downloadFile, extractAllText } from "@/lib/utils";
import { toast } from "sonner";

export function ExportMenu() {
  const { documentData, currentFile, currentPage } = useViewerStore();
  const [isExporting, setIsExporting] = useState(false);

  const exportAsJSON = (fullDocument: boolean = true) => {
    if (!documentData || !currentFile) return;

    try {
      setIsExporting(true);
      const data = fullDocument
        ? documentData
        : { pages: [documentData.pages.find((p) => p.page_number === currentPage)] };

      const jsonString = JSON.stringify(data, null, 2);
      const fileName = fullDocument
        ? `${currentFile.name}_complete.json`
        : `${currentFile.name}_page${currentPage}.json`;

      downloadFile(jsonString, fileName, "application/json");
      toast.success(`Exported as ${fileName}`);
    } catch (error) {
      toast.error("Failed to export JSON");
    } finally {
      setIsExporting(false);
    }
  };

  const exportAsMarkdown = (fullDocument: boolean = true) => {
    if (!documentData || !currentFile) return;

    try {
      setIsExporting(true);
      const pages = fullDocument
        ? documentData.pages
        : [documentData.pages.find((p) => p.page_number === currentPage)!];

      let markdown = "";

      if (documentData.title) {
        markdown += `# ${documentData.title}\n\n`;
      }

      pages.forEach((page) => {
        if (!page) return;

        markdown += `## Page ${page.page_number}\n\n`;

        if (page.header) {
          markdown += `> Header: ${page.header}\n\n`;
        }

        page.text_blocks?.forEach((block) => {
          switch (block.block_type) {
            case "heading":
              markdown += `### ${block.content}\n\n`;
              break;
            case "list_item":
              markdown += `- ${block.content}\n`;
              break;
            case "quote":
              markdown += `> ${block.content}\n\n`;
              break;
            default:
              markdown += `${block.content}\n\n`;
          }
        });

        page.tables?.forEach((table) => {
          if (table.caption) {
            markdown += `**${table.caption}**\n\n`;
          }

          // Table headers
          if (table.headers.length > 0) {
            markdown += "| " + table.headers.map((h) => h.content).join(" | ") + " |\n";
            markdown += "| " + table.headers.map(() => "---").join(" | ") + " |\n";
          }

          // Table rows
          table.rows.forEach((row) => {
            markdown += "| " + row.map((cell) => cell.content).join(" | ") + " |\n";
          });

          markdown += "\n";
        });

        if (page.footer) {
          markdown += `> Footer: ${page.footer}\n\n`;
        }

        markdown += "---\n\n";
      });

      const fileName = fullDocument
        ? `${currentFile.name}_complete.md`
        : `${currentFile.name}_page${currentPage}.md`;

      downloadFile(markdown, fileName, "text/markdown");
      toast.success(`Exported as ${fileName}`);
    } catch (error) {
      toast.error("Failed to export Markdown");
    } finally {
      setIsExporting(false);
    }
  };

  const exportAsPlainText = (fullDocument: boolean = true) => {
    if (!documentData || !currentFile) return;

    try {
      setIsExporting(true);
      const pages = fullDocument
        ? documentData.pages
        : [documentData.pages.find((p) => p.page_number === currentPage)!];

      let text = "";

      if (documentData.title) {
        text += `${documentData.title}\n${"=".repeat(documentData.title.length)}\n\n`;
      }

      pages.forEach((page) => {
        if (!page) return;

        text += `Page ${page.page_number}\n${"-".repeat(20)}\n\n`;

        if (page.header) {
          text += `[Header: ${page.header}]\n\n`;
        }

        page.text_blocks?.forEach((block) => {
          text += `${block.content}\n\n`;
        });

        page.tables?.forEach((table) => {
          if (table.caption) {
            text += `${table.caption}\n`;
          }

          table.rows.forEach((row) => {
            text += row.map((cell) => cell.content).join(" | ") + "\n";
          });

          text += "\n";
        });

        if (page.footer) {
          text += `[Footer: ${page.footer}]\n\n`;
        }

        text += "\n";
      });

      const fileName = fullDocument
        ? `${currentFile.name}_complete.txt`
        : `${currentFile.name}_page${currentPage}.txt`;

      downloadFile(text, fileName, "text/plain");
      toast.success(`Exported as ${fileName}`);
    } catch (error) {
      toast.error("Failed to export text");
    } finally {
      setIsExporting(false);
    }
  };

  const exportAsHTML = () => {
    if (!documentData || !currentFile) return;

    try {
      setIsExporting(true);

      let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${documentData.title || currentFile.name}</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      line-height: 1.6;
      max-width: 800px;
      margin: 0 auto;
      padding: 20px;
      color: #333;
    }
    .page {
      margin-bottom: 40px;
      page-break-after: always;
    }
    .page-header {
      color: #666;
      font-size: 0.9em;
      border-bottom: 1px solid #ddd;
      padding-bottom: 5px;
      margin-bottom: 20px;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      margin: 20px 0;
    }
    th, td {
      border: 1px solid #ddd;
      padding: 8px 12px;
      text-align: left;
    }
    th {
      background-color: #f4f4f4;
      font-weight: bold;
    }
    .footer {
      color: #666;
      font-size: 0.9em;
      border-top: 1px solid #ddd;
      padding-top: 5px;
      margin-top: 20px;
    }
  </style>
</head>
<body>
`;

      if (documentData.title) {
        html += `  <h1>${documentData.title}</h1>\n`;
      }

      documentData.pages.forEach((page) => {
        html += `  <div class="page" id="page-${page.page_number}">\n`;
        html += `    <div class="page-header">Page ${page.page_number}</div>\n`;

        if (page.header) {
          html += `    <p><em>${page.header}</em></p>\n`;
        }

        page.text_blocks?.forEach((block) => {
          const tag = block.block_type === "heading" ? "h2" : "p";
          const dir = block.text_direction || "ltr";
          html += `    <${tag} dir="${dir}">${block.content}</${tag}>\n`;
        });

        page.tables?.forEach((table) => {
          html += `    <table>\n`;

          if (table.caption) {
            html += `      <caption>${table.caption}</caption>\n`;
          }

          if (table.headers.length > 0) {
            html += `      <thead>\n        <tr>\n`;
            table.headers.forEach((header) => {
              html += `          <th>${header.content}</th>\n`;
            });
            html += `        </tr>\n      </thead>\n`;
          }

          html += `      <tbody>\n`;
          table.rows.forEach((row) => {
            html += `        <tr>\n`;
            row.forEach((cell) => {
              html += `          <td>${cell.content}</td>\n`;
            });
            html += `        </tr>\n`;
          });
          html += `      </tbody>\n`;
          html += `    </table>\n`;
        });

        if (page.footer) {
          html += `    <div class="footer">${page.footer}</div>\n`;
        }

        html += `  </div>\n`;
      });

      html += `</body>\n</html>`;

      downloadFile(html, `${currentFile.name}_export.html`, "text/html");
      toast.success("Exported as HTML");
    } catch (error) {
      toast.error("Failed to export HTML");
    } finally {
      setIsExporting(false);
    }
  };

  if (!documentData || !currentFile) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2" disabled={isExporting}>
          <Download className="h-4 w-4" />
          Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Export Document</DropdownMenuLabel>
        <DropdownMenuSeparator />

        <DropdownMenuItem onClick={() => exportAsJSON(true)}>
          <FileJson className="mr-2 h-4 w-4" />
          Full Document (JSON)
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => exportAsJSON(false)}>
          <FileJson className="mr-2 h-4 w-4" />
          Current Page (JSON)
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem onClick={() => exportAsMarkdown(true)}>
          <FileCode className="mr-2 h-4 w-4" />
          Full Document (Markdown)
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => exportAsMarkdown(false)}>
          <FileCode className="mr-2 h-4 w-4" />
          Current Page (Markdown)
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem onClick={() => exportAsPlainText(true)}>
          <FileText className="mr-2 h-4 w-4" />
          Full Document (Text)
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => exportAsPlainText(false)}>
          <FileText className="mr-2 h-4 w-4" />
          Current Page (Text)
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem onClick={exportAsHTML}>
          <FileCode className="mr-2 h-4 w-4" />
          Export as HTML
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
